# Deploying Experimently Marketing Website with AWS Route 53

This guide covers deploying your marketing website using AWS services with Route 53 for DNS management.

!!! warning "What this page is, and what exists today"
    This page is about hosting the project's **marketing site**
    (`getexperimently.com`), not about running a self-hosted Experimently. That
    site is built by AWS Amplify from [`amplify.yml`](https://github.com/getexperimently/experimently/blob/main/amplify.yml)
    at the repository root. The options below are ways that site *could* be
    hosted; none of them is created by the CDK in `infrastructure/cdk`.

    **The dashboard is not yet deployed by the CDK.** The CDK's Fargate stack
    runs the API behind an Application Load Balancer and nothing else, so there
    is no dashboard for an `app.` subdomain to point at (#69). The
    documentation is published to GitHub Pages, not CloudFront and S3.

## Architecture Overview

```
Route 53 (DNS)
├── getexperimently.com          → CloudFront → S3, or Amplify (Marketing Site)
├── www.getexperimently.com      → CloudFront → S3 (Redirect to apex)
└── api.getexperimently.com      → ALB → ECS (Backend API, the CDK's Fargate stack)
```

Not provided today: an `app.` subdomain for the dashboard (the CDK does not
deploy one), and a `docs.` subdomain (the documentation is on GitHub Pages).

## Deployment Options

### Option 1: AWS Amplify (Recommended - Easiest)

**Pros:**
- Automatic CI/CD from GitHub
- SSL certificate auto-configured
- Easy Route 53 integration
- Preview deployments
- Free tier available

**Cons:**
- Less control than CloudFront
- Vendor lock-in

### Option 2: CloudFront + S3 (Most Control)

**Pros:**
- Full control over caching
- Lowest cost at scale
- Integrates perfectly with Route 53
- Best performance

**Cons:**
- More setup required
- Manual deployment process

### Option 3: Vercel with Route 53 (Hybrid)

**Pros:**
- Best developer experience
- Automatic deployments
- Great Next.js optimization

**Cons:**
- Requires CNAME to Vercel (external dependency)

---

## 🚀 Deployment Method 1: AWS Amplify (Recommended)

### Step 1: Install AWS Amplify CLI

```bash
npm install -g @aws-amplify/cli
amplify configure
```

### Step 2: Initialize Amplify in Your Project

```bash
cd frontend
amplify init
```

**Configuration:**
```
? Enter a name for the project: experimently-web
? Enter a name for the environment: prod
? Choose your default editor: Visual Studio Code
? Choose the type of app: javascript
? What javascript framework: react
? Source Directory Path: src
? Distribution Directory Path: out
? Build Command: npm run build:marketing
? Start Command: npm run start
```

### Step 3: Add Hosting

```bash
amplify add hosting
```

**Choose:**
- Hosting with Amplify Console (Managed hosting with CI/CD)
- Manual deployment

### Step 4: Configure Custom Domain in Amplify Console

1. Go to [AWS Amplify Console](https://console.aws.amazon.com/amplify/)
2. Select your app
3. Go to "Domain management"
4. Click "Add domain"
5. Select `getexperimently.com` from Route 53 hosted zones
6. Add subdomains:
   - ☑ `getexperimently.com` (apex)
   - ☑ `www.getexperimently.com`
7. Click "Configure domain"

**Amplify will automatically:**
- Create SSL certificate (ACM)
- Configure Route 53 A/AAAA records
- Set up www redirect
- Configure CloudFront distribution

### Step 5: Connect GitHub Repository

1. In Amplify Console, go to "App settings" → "Build settings"
2. Connect your GitHub repository
3. Select branch: `main`
4. Build settings (auto-detected):

```yaml
version: 1
frontend:
  phases:
    preBuild:
      commands:
        - cd frontend
        - npm ci
    build:
      commands:
        - npm run build:marketing   # NOT `npm run build`: that ships the dashboard
  artifacts:
    # `output: 'export'` in next.config.js, so the artefact is out/, not .next
    baseDirectory: frontend/out
    files:
      - '**/*'
  cache:
    paths:
      - frontend/node_modules/**/*
```

### Step 6: Deploy

```bash
# Amplify auto-deploys on git push, or manually:
amplify publish
```

**Your site will be live at:**
- https://getexperimently.com
- https://www.getexperimently.com (redirects to apex)

---

## 🔧 Deployment Method 2: CloudFront + S3 (Advanced)

### Prerequisites

```bash
# Install AWS CLI
brew install awscli  # macOS
# or
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Configure AWS credentials
aws configure
```

### Step 1: Build Next.js for Static Export

Update `frontend/next.config.js`:

```javascript
/** @type {import('next').NextConfig} */
module.exports = {
  reactStrictMode: true,
  output: 'export',  // Enable static export
  images: {
    unoptimized: true,  // Required for static export
  },
}
```

Build the site:

```bash
cd frontend
npm run build:marketing   # NOT `npm run build`: that ships the dashboard
# Output will be in 'out' directory
```

### Step 2: Create S3 Bucket

```bash
# Create bucket (bucket name must match domain)
aws s3 mb s3://getexperimently.com --region us-east-1

# Enable static website hosting
aws s3 website s3://getexperimently.com \
  --index-document index.html \
  --error-document 404.html
```

### Step 3: Create Bucket Policy

Create `bucket-policy.json`:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "PublicReadGetObject",
      "Effect": "Allow",
      "Principal": "*",
      "Action": "s3:GetObject",
      "Resource": "arn:aws:s3:::getexperimently.com/*"
    }
  ]
}
```

Apply policy:

```bash
aws s3api put-bucket-policy \
  --bucket getexperimently.com \
  --policy file://bucket-policy.json
```

### Step 4: Upload Website Files

```bash
cd frontend

# Sync built files to S3
aws s3 sync out/ s3://getexperimently.com \
  --delete \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*.html" \
  --exclude "*.json"

# Upload HTML with shorter cache
aws s3 sync out/ s3://getexperimently.com \
  --delete \
  --cache-control "public, max-age=0, must-revalidate" \
  --exclude "*" \
  --include "*.html" \
  --include "*.json"
```

### Step 5: Request SSL Certificate (ACM)

**IMPORTANT**: Certificate for CloudFront must be in `us-east-1` region.

```bash
# Request certificate
aws acm request-certificate \
  --domain-name getexperimently.com \
  --subject-alternative-names "*.getexperimently.com" \
  --validation-method DNS \
  --region us-east-1

# Note the CertificateArn from output
```

### Step 6: Validate Certificate with Route 53

1. Go to [ACM Console](https://console.aws.amazon.com/acm/) (us-east-1 region)
2. Click on your certificate
3. Click "Create records in Route 53" button
4. This automatically adds CNAME records for validation
5. Wait 5-10 minutes for validation to complete

### Step 7: Create CloudFront Distribution

Create `cloudfront-config.json`:

```json
{
  "CallerReference": "experimently-marketing-2025",
  "Aliases": {
    "Quantity": 2,
    "Items": ["getexperimently.com", "www.getexperimently.com"]
  },
  "DefaultRootObject": "index.html",
  "Origins": {
    "Quantity": 1,
    "Items": [
      {
        "Id": "S3-getexperimently.com",
        "DomainName": "getexperimently.com.s3-website-us-east-1.amazonaws.com",
        "CustomOriginConfig": {
          "HTTPPort": 80,
          "HTTPSPort": 443,
          "OriginProtocolPolicy": "http-only"
        }
      }
    ]
  },
  "DefaultCacheBehavior": {
    "TargetOriginId": "S3-getexperimently.com",
    "ViewerProtocolPolicy": "redirect-to-https",
    "AllowedMethods": {
      "Quantity": 2,
      "Items": ["GET", "HEAD"]
    },
    "ForwardedValues": {
      "QueryString": false,
      "Cookies": {
        "Forward": "none"
      }
    },
    "MinTTL": 0,
    "DefaultTTL": 86400,
    "MaxTTL": 31536000,
    "Compress": true
  },
  "Comment": "Experimently Marketing Website",
  "PriceClass": "PriceClass_100",
  "Enabled": true,
  "ViewerCertificate": {
    "ACMCertificateArn": "arn:aws:acm:us-east-1:ACCOUNT_ID:certificate/CERT_ID",
    "SSLSupportMethod": "sni-only",
    "MinimumProtocolVersion": "TLSv1.2_2021"
  },
  "CustomErrorResponses": {
    "Quantity": 1,
    "Items": [
      {
        "ErrorCode": 404,
        "ResponsePagePath": "/404.html",
        "ResponseCode": "404",
        "ErrorCachingMinTTL": 300
      }
    ]
  }
}
```

**Update the ACMCertificateArn** with your certificate ARN, then create:

```bash
aws cloudfront create-distribution \
  --distribution-config file://cloudfront-config.json \
  > cloudfront-output.json

# Note the Distribution ID and Domain Name from output
```

### Step 8: Configure Route 53

Get your CloudFront distribution domain:

```bash
# From cloudfront-output.json, note the DomainName (e.g., d1234abcd.cloudfront.net)
```

Create Route 53 records:

```bash
# Get your hosted zone ID
aws route53 list-hosted-zones

# Create A record for apex domain
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "getexperimently.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "d1234abcd.cloudfront.net",
          "EvaluateTargetHealth": false
        }
      }
    }]
  }'

# Create A record for www subdomain
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "www.getexperimently.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "Z2FDTNDATAQYW2",
          "DNSName": "d1234abcd.cloudfront.net",
          "EvaluateTargetHealth": false
        }
      }
    }]
  }'
```

**Note**: `Z2FDTNDATAQYW2` is always the HostedZoneId for CloudFront distributions.

### Step 9: Test Your Deployment

```bash
# Wait for DNS propagation (5-10 minutes)
# Test your site
curl -I https://getexperimently.com
curl -I https://www.getexperimently.com
```

---

## 🔧 Deployment Method 3: Vercel with Route 53

### Step 1: Deploy to Vercel

```bash
cd frontend
npm install -g vercel
vercel
```

Follow the prompts:
- Set up and deploy: Yes
- Scope: Your account
- Link to existing project: No
- Project name: experimently-marketing
- Directory: ./
- Override settings: No

### Step 2: Add Custom Domain in Vercel

1. Go to [Vercel Dashboard](https://vercel.com/dashboard)
2. Select your project
3. Go to Settings → Domains
4. Add `getexperimently.com`
5. Add `www.getexperimently.com`

Vercel will show DNS records to configure.

### Step 3: Configure Route 53

**For apex domain (getexperimently.com):**

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "getexperimently.com",
        "Type": "A",
        "TTL": 300,
        "ResourceRecords": [
          {"Value": "76.76.21.21"}
        ]
      }
    }]
  }'
```

**For www subdomain:**

```bash
aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "www.getexperimently.com",
        "Type": "CNAME",
        "TTL": 300,
        "ResourceRecords": [
          {"Value": "cname.vercel-dns.com"}
        ]
      }
    }]
  }'
```

**Note**: Use the actual IP and CNAME values provided by Vercel.

---

## 📋 Configure Other Subdomains

### app.getexperimently.com — not provided today

The CDK does not deploy the dashboard, so there is no load balancer or
distribution for an `app.` record to point at (#69).

### api.getexperimently.com (ECS/ALB)

The CDK's Fargate stack creates one Application Load Balancer, in front of the
API.

```bash
# Get your ALB DNS name and its hosted zone (both are per region)
ALB_DNS="your-alb-name.us-west-2.elb.amazonaws.com"
ALB_ZONE_ID="Z1H1FL5HABSF5"  # ALB hosted zone for us-west-2

aws route53 change-resource-record-sets \
  --hosted-zone-id YOUR_HOSTED_ZONE_ID \
  --change-batch '{
    "Changes": [{
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "api.getexperimently.com",
        "Type": "A",
        "AliasTarget": {
          "HostedZoneId": "'$ALB_ZONE_ID'",
          "DNSName": "'$ALB_DNS'",
          "EvaluateTargetHealth": true
        }
      }
    }]
  }'
```

### Documentation

The documentation is built with MkDocs and published to GitHub Pages by
`.github/workflows/docs.yml`; it has no `docs.` subdomain and no CloudFront or
S3 behind it.

---

## 🔒 SSL Certificates Summary

### For CloudFront Distributions (Marketing site, if you choose CloudFront)
- **Region**: Must be in `us-east-1`
- **Certificate**: `*.getexperimently.com` and `getexperimently.com`

### For ALB (API)
- **Region**: Same as your ALB (e.g., `us-west-2`)
- **Certificate**: `*.getexperimently.com` and `getexperimently.com`

**Request both certificates:**

```bash
# For CloudFront (us-east-1)
aws acm request-certificate \
  --domain-name getexperimently.com \
  --subject-alternative-names "*.getexperimently.com" \
  --validation-method DNS \
  --region us-east-1

# For ALB (your region, e.g., us-west-2)
aws acm request-certificate \
  --domain-name getexperimently.com \
  --subject-alternative-names "*.getexperimently.com" \
  --validation-method DNS \
  --region us-west-2
```

---

## 🚀 Automated Deployment Script

Create `deploy-marketing.sh`:

```bash
#!/bin/bash
set -e

echo "Building marketing site..."
cd frontend
npm run build:marketing   # NOT `npm run build`: that ships the dashboard

echo "Uploading to S3..."
aws s3 sync out/ s3://getexperimently.com \
  --delete \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*.html" \
  --exclude "*.json"

aws s3 sync out/ s3://getexperimently.com \
  --delete \
  --cache-control "public, max-age=0, must-revalidate" \
  --exclude "*" \
  --include "*.html" \
  --include "*.json"

echo "Invalidating CloudFront cache..."
DISTRIBUTION_ID=$(aws cloudfront list-distributions \
  --query "DistributionList.Items[?Aliases.Items[?contains(@, 'getexperimently.com')]].Id" \
  --output text)

aws cloudfront create-invalidation \
  --distribution-id $DISTRIBUTION_ID \
  --paths "/*"

echo "✅ Deployment complete!"
echo "🌍 Visit: https://getexperimently.com"
```

Make it executable:

```bash
chmod +x deploy-marketing.sh
./deploy-marketing.sh
```

---

## 📊 Monitoring & Analytics

### CloudWatch Metrics (CloudFront)

View in CloudWatch Console:
- Requests
- Bytes Downloaded
- Error Rate
- Cache Hit Rate

### Set Up Alarms

```bash
aws cloudwatch put-metric-alarm \
  --alarm-name experimently-marketing-4xx-errors \
  --alarm-description "Alert on 4xx errors" \
  --metric-name 4xxErrorRate \
  --namespace AWS/CloudFront \
  --statistic Average \
  --period 300 \
  --evaluation-periods 2 \
  --threshold 5 \
  --comparison-operator GreaterThanThreshold
```

---

## 🎯 Recommended Setup

**For your use case, I recommend:**

1. **Marketing Site** (`getexperimently.com`): AWS Amplify (what `amplify.yml` builds today) or CloudFront + S3
2. **API** (`api.getexperimently.com`): ECS/Fargate + ALB, created by the CDK's Fargate stack
3. **App Dashboard**: not provided today. The CDK does not deploy the dashboard (#69).
4. **Docs**: GitHub Pages, from `.github/workflows/docs.yml`

**Quick Start:**
```bash
# Option 1: Use Amplify (easiest)
npm install -g @aws-amplify/cli
cd frontend
amplify init
amplify add hosting
amplify publish

# Option 2: Use CloudFront + S3 (most control)
# Follow steps in "Deployment Method 2" above
```

---

## 📞 Need Help?

Check your Route 53 configuration:
```bash
aws route53 list-resource-record-sets --hosted-zone-id YOUR_HOSTED_ZONE_ID
```

Test DNS propagation:
```bash
dig getexperimently.com
nslookup getexperimently.com
```

Test SSL:
```bash
curl -vI https://getexperimently.com
```

---

**Next Steps After Deployment:**
1. ✅ Verify all subdomains resolve correctly
2. ✅ Test SSL certificates on all domains
3. ✅ Set up CloudWatch alarms
4. ✅ Configure Google Analytics
5. ✅ Test from multiple locations/devices

Happy deploying! 🚀
