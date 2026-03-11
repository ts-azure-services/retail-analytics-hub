# Security Checklist — Retail Simulation Workflows

> Based on analysis of `infra/cloud/main.tf`, `infra/local/main.tf`, agent configurations, and data services.

---

## Infrastructure Inventory

| Service | Resource | Current State |
|---------|----------|---------------|
| Microsoft Fabric | Capacity (F8) + Workspace | Deployed |
| Azure Cosmos DB | NoSQL (Session consistency, continuous backup) | Private endpoints in prod |
| Azure PostgreSQL | Flexible Server v16, AD auth enabled | VNET-delegated in prod |
| Azure Event Hubs | Standard tier, SAS auth enabled | Private endpoints in prod |
| Azure OpenAI | S0, GPT-4o-mini + GPT-5.2 deployments | Private endpoints in prod |
| Azure Container Apps | 4 apps (dashboard + 3 agents) + 1 job (importer) | VNET-integrated in prod |
| Azure Container Registry | Basic (dev) / Premium (prod) | Private endpoints in prod |
| Azure Key Vault | Standard, RBAC-enabled, purge-protected | Private endpoints in prod |
| Azure Storage | LRS staging account (SAS uploads) | Public access enabled |
| Log Analytics | PerGB2018, 30-day retention | Diagnostic settings on most resources |

---

## 1. Network Security & Segmentation

### 1A — Private Endpoints for All Data Services

| Item | Status | Notes |
|------|--------|-------|
| Cosmos DB private endpoint (SQL sub-resource) | ✅ Prod | `pe-cosmosdb-*`, DNS zone `privatelink.documents.azure.com` |
| PostgreSQL VNET delegation | ✅ Prod | Delegated subnet `snet-postgresql` (10.0.2.0/24) |
| Event Hub private endpoint | ✅ Prod | `pe-eventhub-*`, DNS zone `privatelink.servicebus.windows.net` |
| Azure OpenAI private endpoint | ✅ Prod | `pe-cognitive-*`, DNS zone `privatelink.cognitiveservices.azure.com` |
| Key Vault private endpoint | ✅ Prod | `pe-keyvault-*`, isolated subnet `snet-keyvault-pe` (10.0.4.0/28) |
| ACR private endpoint | ✅ Prod | `pe-acr-*`, DNS zone `privatelink.azurecr.io` |
| **Storage Account private endpoint** | ⬜ Missing | `staging*` storage has `public_network_access_enabled = true` with no PE defined — add `privatelink.blob.core.windows.net` PE |
| **Azure OpenAI (local/main.tf)** | ⬜ Missing | `public_network_access_enabled = true`, no VNET, no PE — acceptable for dev but needs hardening for any shared use |
| Disable public access on all services after PE creation | ⬜ Partial | Key Vault still has `public_network_access_enabled = true` and `default_action = Allow` even in prod |

### 1B — VNET-Integrated Container Apps

| Item | Status | Notes |
|------|--------|-------|
| Container App Environment VNET integration | ✅ Prod | `infrastructure_subnet_id` set to `snet-containerapp` (10.0.0.0/23) |
| Internal load balancer for agents | ✅ Agents | Agent ingress `external_enabled = false` |
| Dashboard external exposure minimized | ⚠️ Review | Dashboard `external_enabled = true` — consider Front Door or App Gateway with WAF |

### 1C — Network Segmentation (Subnets & NSGs)

| Item | Status | Notes |
|------|--------|-------|
| **Data tier** — PostgreSQL subnet with NSG | ✅ | `snet-postgresql` (10.0.2.0/24), NSG allows 5432 from container app + management only, deny-all default |
| **Compute tier** — Container App subnet with NSG | ✅ | `snet-containerapp` (10.0.0.0/23), NSG allows HTTPS/HTTP in, scoped outbound |
| **Integration tier** — Private endpoints subnet with NSG | ✅ | `snet-privateendpoints` (10.0.3.0/24), NSG allows HTTPS from compute + data |
| **Key Vault** — Isolated PE subnet with NSG | ✅ | `snet-keyvault-pe` (10.0.4.0/28), deny internet inbound |
| **Management** — Future management subnet | ✅ | `snet-management` (10.0.5.0/24) reserved |
| **Fabric private endpoints** — Dedicated subnet | ⬜ Missing | No Fabric VNET connectivity defined; add subnet for Fabric managed PE when using OneLake/Spark from VNET |
| NSG flow logs enabled | ⬜ Missing | Add `azurerm_network_watcher_flow_log` for each NSG to capture traffic analytics |
| Deny all outbound Internet by default | ⬜ Missing | Container App NSG allows `Internet` outbound (priority 130) — tighten to Azure service tags only |

---

## 2. Identity & Access Management

### 2A — Managed Identities

| Item | Status | Notes |
|------|--------|-------|
| Container Apps — System-Assigned MI | ✅ | All 4 apps + importer job have `identity { type = "SystemAssigned" }` |
| PostgreSQL — System-Assigned MI | ✅ | `identity { type = "SystemAssigned" }` enabled |
| ACR pull via MI (no admin) | ✅ | `admin_enabled = false`, AcrPull role assigned to all app MIs |
| OpenAI access via MI | ✅ | `Cognitive Services OpenAI User` role for agents 1–3 |
| Cosmos DB access via MI | ✅ Importer | Custom Data Contributor role assigned to importer MI |
| Event Hub access via MI | ✅ Importer | `Azure Event Hubs Data Sender` role for importer |
| Key Vault access via RBAC | ✅ | `rbac_authorization_enabled = true`, KV Admin for deployer |
| **Dashboard MI → Fabric SQL** | ⬜ Missing | Dashboard passes `FABRIC_SQL_ENDPOINT` but no role assignment for its MI to query Fabric |
| **Agent MIs → Key Vault secrets** | ⬜ Missing | No Key Vault Secrets User role for agent MIs — needed if agents read secrets at runtime |
| **Storage Account MI access** | ⬜ Missing | Staging storage has no MI-based access for upload pipeline (relies on SAS) — add Blob Data Contributor for sync pipeline MI |
| **Eliminate service principal secrets in local.env** | 🔴 Critical | `AZURE_CLIENT_SECRET` is stored in plaintext in `local.env` — rotate immediately, use DefaultAzureCredential without embedded secrets |

### 2B — Fabric Workspace Identity & Access

| Item | Status | Notes |
|------|--------|-------|
| Enable Fabric workspace identity | ⬜ Not configured | Add `fabric_workspace_identity` for secure connections to Azure data sources |
| Implement trusted workspace access | ⬜ Not configured | Configure firewall-protected resources (Storage, SQL) to trust Fabric workspace identity |
| Fabric capacity admin restricted | ✅ | Single UPN via `administration_members` variable |
| Workspace RBAC (viewer/contributor/admin) | ⬜ Not configured | Define Fabric workspace role assignments in Terraform |

### 2C — Conditional Access & Authentication

| Item | Status | Notes |
|------|--------|-------|
| Entra ID Conditional Access for Fabric | ⬜ Not configured | Require compliant device, MFA, and approved locations for Fabric portal access |
| PostgreSQL AD auth | ✅ | `active_directory_auth_enabled = true` |
| PostgreSQL password auth | ⚠️ Review | `password_auth_enabled = true` — consider disabling after all clients use AD auth |
| Event Hub local (SAS) auth | ⚠️ Review | `local_authentication_enabled = true` for Fabric Eventstream — restrict SAS policy scope |
| MFA enforcement for all admin roles | ⬜ Not configured | Enforce via Entra ID Conditional Access policies |

---

## 3. Data Protection & Governance

### 3A — Data Classification & Governance (Microsoft Purview)

| Item | Status | Notes |
|------|--------|-------|
| Register Cosmos DB in Purview | ⬜ Not configured | Catalog customer reviews, carts, sessions — contains **PII** (customer names, emails, addresses) |
| Register PostgreSQL in Purview | ⬜ Not configured | Catalog product catalog, transactions, inventory — contains **financial data** |
| Register Fabric Lakehouse in Purview | ⬜ Not configured | Catalog mirrored data, Eventstream outputs |
| Apply sensitivity labels | ⬜ Not configured | Classify PII fields (customer name, email, location) as Confidential |
| Data lineage tracking | ⬜ Not configured | Map flow: Simulation → DuckDB → Staging Storage → Cosmos/Postgres → Fabric Mirror → OneLake |
| Define data retention policies | ⬜ Not configured | Align Event Hub (3-day retention) with business/regulatory requirements |

### 3B — OneLake Security (Least Privilege)

| Item | Status | Notes |
|------|--------|-------|
| OneLake workspace-level access control | ⬜ Not configured | Restrict OneLake data access to workspace members only |
| Item-level permissions in Lakehouse | ⬜ Not configured | Separate read-only analyst roles from pipeline writer roles |
| OneLake shortcut security review | ⬜ Not configured | Ensure shortcuts to external data inherit proper auth |
| Row-level / column-level security in Fabric SQL | ⬜ Not configured | Protect PII columns in mirrored PostgreSQL data |

### 3C — Encryption & Secrets

| Item | Status | Notes |
|------|--------|-------|
| Cosmos DB encryption at rest | ✅ | Default Microsoft-managed keys |
| PostgreSQL encryption at rest | ✅ | Default Microsoft-managed keys |
| Storage encryption at rest | ✅ | Default Microsoft-managed keys |
| Key Vault purge protection | ✅ | `purge_protection_enabled = true` |
| Key Vault soft delete | ✅ | 7-day retention |
| **Customer-managed keys (CMK)** | ⬜ Not configured | Consider CMK for Cosmos DB, PostgreSQL, Storage if handling sensitive retail data |
| **TLS enforcement** | ✅ Partial | PostgreSQL uses default TLS; verify `ssl_enforcement_enabled` and minimum TLS 1.2 across all services |
| Secrets stored in Key Vault | ✅ | PostgreSQL password, Cosmos DB keys, Event Hub keys all in KV |
| **Terraform state file secrets** | 🔴 Critical | `terraform.tfstate` is local and contains all secrets in plaintext — migrate to Azure Storage backend with encryption |

---

## 4. Threat Protection & Monitoring

### 4A — Microsoft Defender for Cloud

| Item | Status | Notes |
|------|--------|-------|
| Defender for Cosmos DB | ⬜ Not enabled | Enable `azurerm_security_center_subscription_pricing` for CosmosDb |
| Defender for PostgreSQL (Open-Source Relational DBs) | ⬜ Not enabled | Detects anomalous access, SQL injection, brute force |
| Defender for Storage | ⬜ Not enabled | Detects unusual access patterns, malware uploads |
| Defender for Key Vault | ⬜ Not enabled | Detects unusual secret access and high-volume operations |
| Defender for Containers | ⬜ Not enabled | Scans ACR images for vulnerabilities, runtime protection |
| Defender for Azure OpenAI (AI threat protection) | ⬜ Not enabled | Monitor for prompt injection, data exfiltration via AI |
| Defender for Resource Manager | ⬜ Not enabled | Detects suspicious management operations |
| **Enable Defender for all resource types** | ⬜ Action needed | Add `azurerm_security_center_subscription_pricing` blocks for each service |

### 4B — Diagnostic Settings & Audit Logging

| Item | Status | Notes |
|------|--------|-------|
| Cosmos DB diagnostics → Log Analytics | ✅ | DataPlaneRequests, QueryRuntime, ControlPlane, etc. |
| PostgreSQL diagnostics → Log Analytics | ✅ | Logs, Sessions, QueryStore, TableStats, Xacts |
| Event Hub diagnostics → Log Analytics | ✅ | Archive, Operational, AutoScale, Kafka, Runtime audit |
| ACR diagnostics → Log Analytics | ✅ | Repository events, Login events |
| **Key Vault diagnostics** | ⬜ Missing | No `azurerm_monitor_diagnostic_setting` for Key Vault — critical for audit trail |
| **Azure OpenAI diagnostics** | ⬜ Missing | No diagnostic setting — add to track prompt/completion logs and token usage |
| **Storage Account diagnostics** | ⬜ Missing | No diagnostic setting for staging storage |
| **Container App Environment diagnostics** | ⬜ Missing | Container Apps Environment logs not explicitly configured |
| **Fabric audit logs** | ⬜ Not configured | Enable Fabric admin audit logging, route to Log Analytics |
| Log Analytics retention | ⚠️ Review | 30 days may be insufficient for compliance — extend to 90+ days for retail |
| Alert rules for security events | ⬜ Not configured | Add `azurerm_monitor_scheduled_query_rules_alert_v2` for failed auth, unusual access patterns |

### 4C — Fabric SaaS Security Features

| Item | Status | Notes |
|------|--------|-------|
| Leverage Fabric built-in SaaS security | ⬜ Review | Fabric handles patching, encryption, availability — document shared responsibility boundaries |
| Fabric audit log integration | ⬜ Not configured | Enable admin monitoring API or stream to Event Hub |
| Fabric data loss prevention (DLP) | ⬜ Not configured | Apply DLP policies to Power BI / Fabric content with sensitivity labels |
| Managed VNETs for Spark workloads | ⬜ Not configured | Enable Fabric managed VNET for Spark to access firewall-protected data services |

---

## 5. Retail Compliance Requirements

### 5A — PCI DSS (Payment Card Industry Data Security Standard)

Required if the system processes, stores, or transmits payment card data.

| Requirement | Mapping to This Infrastructure | Status |
|-------------|-------------------------------|--------|
| **Req 1** — Install and maintain network security controls | VNET segmentation, NSGs, private endpoints | ✅ Prod architecture |
| **Req 2** — Apply secure configurations to all components | Disable default passwords, harden PostgreSQL/Cosmos configs | ⚠️ Review default configs |
| **Req 3** — Protect stored account data | Encryption at rest (check if cardholder data exists in Cosmos/Postgres) | ⬜ Classify data first |
| **Req 4** — Protect cardholder data in transit | TLS 1.2+ for all connections | ⚠️ Verify min TLS version |
| **Req 5** — Protect from malicious software | Defender for Containers (ACR scanning) | ⬜ Not enabled |
| **Req 6** — Develop and maintain secure systems | Secure SDLC, dependency scanning, image vulnerability scanning | ⬜ Not configured |
| **Req 7** — Restrict access by business need to know | RBAC, managed identities, least privilege | ✅ Partial |
| **Req 8** — Identify users and authenticate access | Entra ID, MFA, Conditional Access | ⬜ MFA not enforced |
| **Req 9** — Restrict physical access | Azure data center controls (covered by Azure compliance) | ✅ Azure |
| **Req 10** — Log and monitor all access | Diagnostic settings, Log Analytics | ⚠️ Gaps in KV/OpenAI/Storage |
| **Req 11** — Test security regularly | Penetration testing, vulnerability scanning | ⬜ Not configured |
| **Req 12** — Support information security with policies | Security policies, incident response plan | ⬜ Document required |

### 5B — GDPR / CCPA (Consumer Data Privacy)

Applicable for customer review data, behavioral analytics, and sentiment analysis.

| Requirement | Action Needed | Status |
|-------------|--------------|--------|
| **Data inventory** | Map all PII across Cosmos DB (customers, reviews), PostgreSQL (transactions), Event Hub (real-time events) | ⬜ Use Purview |
| **Lawful basis for processing** | Document consent mechanisms for review collection and sentiment analysis | ⬜ Policy needed |
| **Right to erasure (GDPR Art. 17)** | Implement delete workflows across Cosmos, Postgres, Fabric mirrors, OneLake | ⬜ Not implemented |
| **Right to data portability** | Enable customer data export from all stores | ⬜ Not implemented |
| **Data retention limits** | Define and enforce retention periods per data category | ⬜ Event Hub = 3 days, others undefined |
| **Privacy impact assessment** | Conduct DPIA for AI-driven sentiment analysis on customer reviews | ⬜ Required |
| **Cross-border transfer** | All resources in WestUS3 — document if data subjects are in EU/UK | ⬜ Policy needed |
| **Breach notification** | Configure Defender alerts → incident response within 72 hours (GDPR) / "without unreasonable delay" (CCPA) | ⬜ Not configured |

### 5C — SOC 2 Type II

Relevant for demonstrating operational security of the platform.

| Trust Principle | Mapping | Status |
|----------------|---------|--------|
| **Security** | VNET, NSGs, MI, RBAC, encryption, Defender | ⚠️ Gaps remain |
| **Availability** | Container Apps auto-scale, Cosmos DB continuous backup, PostgreSQL 7-day backup | ✅ Partial |
| **Processing Integrity** | Audit logs, diagnostic settings | ⚠️ Missing KV/OpenAI/Storage logs |
| **Confidentiality** | Private endpoints, KV for secrets, encryption at rest | ⚠️ local.env secret exposure |
| **Privacy** | Purview classification, DLP, data subject rights | ⬜ Not implemented |

### 5D — Industry-Specific Retail Standards

| Standard | Applicability | Status |
|----------|--------------|--------|
| **NRF (National Retail Federation) Cybersecurity Framework** | Align security controls with retail-specific threat landscape | ⬜ Map controls |
| **ISO 27001** | Information security management system — Azure services carry ISO 27001, but tenant-level controls needed | ⬜ Gap analysis |
| **State-specific retail privacy laws** (e.g., California, Virginia, Colorado) | Varying consumer privacy requirements | ⬜ Legal review needed |
| **FTC Act Section 5** (Unfair/Deceptive Practices) | AI-generated sentiment summaries must not mislead consumers | ⬜ Review AI outputs |

---

## 6. Priority Action Items

### 🔴 Critical (Immediate)

1. **Rotate and remove `AZURE_CLIENT_SECRET` from `local.env`** — plaintext service principal secret in source tree
2. **Migrate Terraform state to remote backend** — `terraform.tfstate` contains all secrets in plaintext on disk
3. **Add Key Vault diagnostic settings** — no audit trail for secret access

### 🟡 High (Before Production)

4. Add private endpoint for **Staging Storage Account** + disable public access
5. Disable **Key Vault public network access** in prod (currently `Allow`)
6. Enable **Microsoft Defender** for all resource types (Cosmos, Postgres, Storage, KV, Containers, OpenAI)
7. Add **Azure OpenAI diagnostic settings** (prompt/completion audit trail)
8. Add **Storage Account diagnostic settings**
9. Configure **Fabric workspace identity** for secure Azure connections
10. Add **Container App Environment diagnostics**
11. Extend Log Analytics **retention to 90+ days** for compliance
12. Consider disabling PostgreSQL **password auth** (AD-only)
13. Tighten container app NSG **outbound Internet rule** to Azure service tags

### 🟢 Medium (Compliance Hardening)

14. Deploy **Microsoft Purview** — register Cosmos DB, PostgreSQL, Fabric
15. Implement **OneLake least-privilege** access controls (workspace + item level)
16. Configure **Entra ID Conditional Access** for Fabric portal (MFA, compliant device, location)
17. Enable **Fabric managed VNETs** for Spark workloads
18. Implement **trusted workspace access** for firewall-protected resources
19. Add **NSG flow logs** and traffic analytics
20. Configure **security alert rules** in Log Analytics
21. Implement **GDPR data subject rights** workflows (erasure, portability)
22. Conduct **Privacy Impact Assessment** for AI sentiment analysis
23. Add dedicated **Fabric private endpoint subnet**
24. Implement **customer-managed keys** for sensitive data stores
25. Add **WAF via Azure Front Door** in front of dashboard Container App
