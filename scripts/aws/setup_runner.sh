#!/usr/bin/env bash
# מקים VM קטן ב-AWS il-central-1 (תל אביב) שמשמש כ-self-hosted GitHub Actions
# runner לרפו הזה. המטרה: משיכת דוחות רשות שוק ההון מ-IP ישראלי, אחרי שבדיקת
# ההיתכנות (scripts/cma/probe.py) הראתה חסימת WAF לפי IP על runners של GitHub
# (Azure ארה"ב).
#
# ברירות מחדל שנבחרו:
#   - t4g.small (Graviton, ~$0.0168/hr, ~$12/חודש אם ירוץ 24/7; ARM זול ומספיק
#     לדפדפן headless שרץ מדי פעם).
#   - Amazon Linux 2023 arm64, מפני קטלוג AMI רשמי של AWS.
#   - Security group בלי שום inbound rule (לא SSH, לא כלום) - רק egress.
#     גישה/דיבוג דרך `aws ec2 get-console-output`, לא SSH. אם תרצה SSH בהמשך
#     אפשר להוסיף key pair + inbound rule מוגבל ל-IP שלך.
#   - runner מותקן כ-systemd service (persistent, לא ephemeral) - רץ ברקע
#     ומחכה לג'ובים; אין צורך להריץ אותו ידנית בכל פעם.
#   - runner_token מתקבל דרך GitHub API (POST .../actions/runners/registration-token)
#     ותקף לשעה בלבד - הרץ את הסקריפט מיד אחרי שיצרת אותו.
#
# שימוש:
#   GH_RUNNER_TOKEN=<registration token> ./setup_runner.sh
#
# דרישות מוקדמות: aws cli מוגדר עם credentials שיש להם הרשאות ליצור
# EC2 instance + security group + tags באזור il-central-1.

set -euo pipefail

REGION="il-central-1"
INSTANCE_TYPE="t4g.small"
NAME="maslulim-cma-runner"
REPO_URL="https://github.com/Revach123/MASLULIM"
RUNNER_VERSION="2.319.1"
RUNNER_LABELS="self-hosted,il-central-1"

: "${GH_RUNNER_TOKEN:?חסר GH_RUNNER_TOKEN - צור registration token דרך GitHub API או מההגדרות (Settings > Actions > Runners > New self-hosted runner) והרץ שוב}"

echo "==> בודק זהות AWS..."
aws sts get-caller-identity --region "$REGION" >/dev/null

echo "==> מאתר VPC/subnet ברירת מחדל ב-$REGION..."
VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)
SUBNET_ID=$(aws ec2 describe-subnets --region "$REGION" --filters Name=vpc-id,Values="$VPC_ID" --query 'Subnets[0].SubnetId' --output text)
echo "    VPC=$VPC_ID SUBNET=$SUBNET_ID"

echo "==> מאתר AMI עדכני של Amazon Linux 2023 (arm64)..."
AMI_ID=$(aws ec2 describe-images --region "$REGION" --owners amazon \
  --filters "Name=name,Values=al2023-ami-*-kernel-*-arm64" "Name=state,Values=available" \
  --query 'sort_by(Images,&CreationDate)[-1].ImageId' --output text)
echo "    AMI=$AMI_ID"

echo "==> יוצר/מאתר security group בלי inbound rules (egress בלבד)..."
SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters Name=group-name,Values="${NAME}-sg" Name=vpc-id,Values="$VPC_ID" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "None")
if [ "$SG_ID" = "None" ] || [ -z "$SG_ID" ]; then
  SG_ID=$(aws ec2 create-security-group --region "$REGION" \
    --group-name "${NAME}-sg" --description "CMA self-hosted runner - no inbound" \
    --vpc-id "$VPC_ID" --query 'GroupId' --output text)
fi
echo "    SG=$SG_ID"

USER_DATA=$(mktemp)
cat > "$USER_DATA" <<EOF
#!/bin/bash
set -euo pipefail
dnf install -y python3 python3-pip tar gzip libicu jq
useradd -m -s /bin/bash ghrunner || true
mkdir -p /opt/actions-runner
cd /opt/actions-runner
curl -sSL -o runner.tar.gz "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-arm64-${RUNNER_VERSION}.tar.gz"
tar xzf runner.tar.gz
chown -R ghrunner:ghrunner /opt/actions-runner
sudo -u ghrunner ./config.sh --unattended \\
  --url "${REPO_URL}" \\
  --token "${GH_RUNNER_TOKEN}" \\
  --name "il-central-1-\$(hostname)" \\
  --labels "${RUNNER_LABELS}" \\
  --work _work
./svc.sh install ghrunner
./svc.sh start
EOF

echo "==> מריץ instance..."
INSTANCE_ID=$(aws ec2 run-instances --region "$REGION" \
  --image-id "$AMI_ID" \
  --instance-type "$INSTANCE_TYPE" \
  --subnet-id "$SUBNET_ID" \
  --security-group-ids "$SG_ID" \
  --associate-public-ip-address \
  --user-data "file://$USER_DATA" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${NAME}}]" \
  --metadata-options "HttpTokens=required" \
  --query 'Instances[0].InstanceId' --output text)
rm -f "$USER_DATA"

echo "==> instance נוצר: $INSTANCE_ID"
echo "    ממתין ל-running..."
aws ec2 wait instance-running --region "$REGION" --instance-ids "$INSTANCE_ID"
PUBLIC_IP=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)

echo ""
echo "==> מוכן. instance=$INSTANCE_ID ip=$PUBLIC_IP"
echo "    בדיקה שה-runner נרשם: GitHub -> Settings -> Actions -> Runners"
echo "    (עשוי לקחת 1-2 דקות עד שההתקנה ב-user-data מסיימת)"
echo "    דיבוג בלי SSH: aws ec2 get-console-output --region $REGION --instance-id $INSTANCE_ID"
