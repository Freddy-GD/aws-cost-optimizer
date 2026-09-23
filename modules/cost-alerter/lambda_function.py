import json
import os
import boto3
from datetime import datetime, timezone

ec2 = boto3.client('ec2')
pricing = boto3.client('pricing', region_name='us-east-1')  # Price List API only has an endpoint in us-east-1 (and ap-south-1), regardless of which region's prices you're querying
sns = boto3.client('sns')

# --- Config from environment variables (set on the Lambda, never hardcoded) ---
SNS_TOPIC_ARN = os.environ['SNS_TOPIC_ARN']  # required — fails loudly (KeyError) if not set, on purpose
PRICING_REGION = os.environ.get('PRICING_REGION', 'US East (N. Virginia)')  # Pricing API uses human-readable location names, not region codes like us-east-1
VOLUME_TYPE = os.environ.get('VOLUME_TYPE', 'gp3')


def get_ebs_price_per_gb(volume_type=VOLUME_TYPE, region=PRICING_REGION):
    resp = pricing.get_products(
        ServiceCode='AmazonEC2',
        Filters=[
            {'Type': 'TERM_MATCH', 'Field': 'volumeApiName', 'Value': volume_type},
            {'Type': 'TERM_MATCH', 'Field': 'location', 'Value': region},
            {'Type': 'TERM_MATCH', 'Field': 'productFamily', 'Value': 'Storage'},

        ]
    )
    try: 
        resp_dict = json.loads(resp['PriceList'][0]) 
    except IndexError as e: 
        print (f"Pricing lookup failed: {e}")
        price = 0.08
        return price
    try: 
        ondemand_key = list(resp_dict['terms']['OnDemand'].keys())[0] 
        priceDim_key = list(resp_dict['terms']['OnDemand'][ondemand_key]['priceDimensions'].keys())[0] 
        price_str = resp_dict['terms']['OnDemand'][ondemand_key]['priceDimensions'][priceDim_key]['pricePerUnit']['USD'] 
        price = float(price_str)
        return price
    except (KeyError, ValueError) as e: 
        print (f"Pricing lookup failed: {e}")
        price = 0.08
        return price


def find_waste():
    findings = []
    monthly_waste = 0.0

    # --- 1. Unattached EBS volumes ---
    price_per_gb = get_ebs_price_per_gb()
    vols = ec2.describe_volumes(Filters=[{'Name': 'status', 'Values': ['available']}])['Volumes']
    for v in vols:
        cost = v['Size'] * price_per_gb  # Size is already in GiB, not bytes
        monthly_waste += cost
        findings.append(f"Unattached volume {v['VolumeId']}: {v['Size']}GB, ~${cost:.2f}/mo")

    # --- 2. Idle Elastic IPs ---
    addrs = ec2.describe_addresses()['Addresses']
    # NetworkInterfaceId alone is sufficient here — in VPC (not the deprecated EC2-Classic
    # platform), any EIP with an InstanceId also has a NetworkInterfaceId set, since every
    # VPC instance's IP lives on an ENI. Checking InstanceId separately would be redundant.
    idle_eips = [a for a in addrs if 'NetworkInterfaceId' not in a]
    for a in idle_eips:
        # Simplification: assumes idle for a full 30-day month. Real duration would require
        # querying CloudTrail for the most recent DetachAddress/DisassociateAddress event —
        # planned as a Phase 2 enhancement, not built yet.
        cost = 0.005 * 24 * 30  # verify current EIP hourly rate before trusting this number
        monthly_waste += cost
        findings.append(f"Idle Elastic IP {a['PublicIp']}: ~${cost:.2f}/mo (assumes idle 30 days)")

    # --- 3. Stopped instances (still billed for attached storage) ---
    stopped = ec2.describe_instances(Filters=[{'Name': 'instance-state-name', 'Values': ['stopped']}])
    for r in stopped['Reservations']:
        for i in r['Instances']:
            findings.append(f"Stopped instance {i['InstanceId']} — still paying for attached storage, review manually")

    return findings, monthly_waste


def lambda_handler(event, context):
    # event: metadata about the EventBridge schedule trigger (unused here — this Lambda
    #   runs the same scan regardless of why it fired)
    # context: Lambda runtime info (request ID, time remaining, log group) — unused here too
    try:
        findings, total = find_waste()

        report = f"Cost audit {datetime.now(timezone.utc):%Y-%m-%d}\n"
        report += f"Estimated monthly waste: ${total:.2f}\n\n"
        report += "\n".join(findings or ["No waste found."])
    except Exception as e: 
        sns.publish(TopicArn=SNS_TOPIC_ARN, Subject='Cost audit FAILED', Message=f"Audit failed: {e}")
        raise
    sns.publish(TopicArn=SNS_TOPIC_ARN, Subject='Weekly cost audit', Message=report)

    return report  # no statusCode/body shape — that's an API Gateway proxy-integration convention, not relevant for a schedule-triggered Lambda with no caller reading the return value