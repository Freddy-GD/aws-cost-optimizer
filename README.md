# AWS Cost-Optimization Auditor

A serverless tool that scans an AWS account for common sources of silent, avoidable cost: unattached EBS volumes, idle Elastic IPs, and stopped EC2 instances, then emails a report with a real, calculated dollar estimate.

## The problem

AWS environments are flexible by design: engineers create resources through the console, CLI, and scripts, and it's easy for something to get provisioned, used, and then simply forgotten. Unlike an obvious ongoing charge like a running EC2 instance, these leftovers are quiet. An unattached EBS volume or an idle Elastic IP doesn't show up anywhere unless someone goes looking for it, and the cost compounds every day it's left alone.

## The solution

A weekly, fully serverless audit:

```
EventBridge (weekly schedule)
        │
        ▼
    Lambda (scans the account)
        │
        ▼
    SNS → email report
        │
        ▼
    Human review & cleanup
```

The Lambda checks for three things on every run:

1. **Unattached EBS volumes** - status `available`, calculated against the real, current AWS gp3 storage rate (pulled live from the AWS Price List API, not hardcoded).
2. **Idle Elastic IPs** - allocated but not attached to any network interface (instance, NAT Gateway, or otherwise).
3. **Stopped EC2 instances** - flagged for manual review, since they still incur EBS storage charges even while stopped.

Deliberately kept human-in-the-loop: the tool surfaces candidates for review, it never auto-deletes anything. An idle-looking Elastic IP might be intentionally reserved for a planned failover; automated deletion based on incomplete signals would be a liability, not a feature.

## Real results

**Test run, August 2026 (original manual version):**

| Finding                   | Detail                          | Estimated cost |
| ------------------------- | ------------------------------- | -------------- |
| Unattached EBS volume     | 4 GB, gp3                       | ~$0.32/mo      |
| Idle Elastic IP           | 1 address, assumed idle 30 days | ~$3.60/mo      |
| **Total estimated waste** |                                 | **$3.92/mo**   |

**Test run, September 2026 (current Terraform-managed version):**

| Finding                   | Detail                          | Estimated cost |
| ------------------------- | ------------------------------- | -------------- |
| Unattached volume         | 1 GB, gp3                       | ~$0.08/mo      |
| Idle Elastic IP           | 1 address, assumed idle 30 days | ~$3.60/mo      |
| **Total estimated waste** |                                 | **$3.68/mo**   |

Both runs are calculated against AWS's actual published pricing where possible. EBS pricing is queried live from the AWS Price List API. EIP idle cost uses a verified constant rather than a live lookup, documented under Known limitations below.

## Architecture / stack

- **AWS Lambda** (Python 3.12, boto3): the scan logic
- **Amazon EventBridge**: weekly schedule trigger (`rate(7 days)`)
- **Amazon SNS**: email delivery of the report
- **AWS Price List API**: live gp3 storage pricing, not a hardcoded constant
- **IAM**: least-privilege inline policy scoped to `ec2:Describe*`, `pricing:GetProducts`, `sns:Publish`
- **Terraform**: infrastructure (Lambda, IAM role/policy, EventBridge rule/target, SNS topic/subscription) provisioned as code, organized as a reusable module; remote state managed on HCP Terraform with dynamic AWS credentials (OIDC)

## Engineering decisions worth knowing about

**Caught and fixed a real pricing bug.** The first working version returned $0.005/GB instead of the correct $0.08/GB for gp3 storage, off by roughly 16x. Root cause: the AWS Pricing API filter only constrained on `volumeApiName` and `location`, which can match multiple products for the same volume type (storage, provisioned IOPS, and provisioned throughput are separate priced dimensions for gp3). Fixed by adding an explicit `productFamily: Storage` filter, then verified the corrected output against AWS's published rate before trusting the number.

**Found a second, unrelated bug during the Terraform migration.** `get_ebs_price_per_gb()`'s success path was missing a `return` statement. It worked by accident whenever the pricing lookup happened to fail and fall back to a hardcoded default, but crashed with `TypeError: unsupported operand type(s) for *: 'int' and 'NoneType'` the moment a real pricing lookup succeeded and any unattached volume existed to price. Caught by actually invoking the function end-to-end rather than trusting a clean deploy.

**Idle Elastic IP check simplified from two conditions to one.** Originally checked for the absence of both `InstanceId` and `NetworkInterfaceId`. Confirmed against AWS documentation that in the VPC platform (not the deprecated EC2-Classic platform), any EIP with an `InstanceId` always has a `NetworkInterfaceId` too, since every VPC instance's address lives on an ENI. The `InstanceId` check was redundant legacy logic and was removed.

**Config is environment-driven, not hardcoded.** The SNS topic ARN, pricing region, and volume type are all read from Lambda environment variables, not embedded in the code, so the same code works unchanged across environments if rebuilt or redeployed.

**Handler fails loudly instead of failing silently.** The whole
