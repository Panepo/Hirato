## Plan: Email Processing Pipeline Integration

This plan outlines the implementation of an email processing system that receives emails sent to `{ChannelName}@swai.getac.com.tw`, uses the existing LLM pipeline to classify content as "save_memory" or "answer_question", saves memories to LanceDB, and replies to questions via email.

**Mail Service Hosting**
The server will host its own mail service to receive and send emails by itself, rather than relying on external IMAP/SMTP servers. This involves running a Mail Transfer Agent (MTA) like Postfix and an IMAP server like Dovecot (or using a containerized mail server solution). The server will listen on standard mail ports:
- SMTP (receiving incoming mail): Listens on port 25 (SMTP)
- SMTP (submission for internal services): Listens on port 587 (SMTP Submission) or 465 (SMTPS)
- IMAP (for mail retrieval): Listens on port 993 (IMAPS) or 143 (IMAP)
- Web server (FastAPI): Listens on port 7950 for HTTP/HTTPS requests

**Steps**

**Phase 1: Mail Service Configuration & Setup**
1. Add mail service configuration settings to `app/core/config.py` — Add mail service configuration fields (local mail server host/port, email channel identifier, default channel name mapping, sender email address)
2. Set up local mail server services — Configure and run a Mail Transfer Agent (MTA) like Postfix for sending/receiving emails and an IMAP server like Dovecot for mail retrieval, or use a containerized mail server solution (e.g., `docker-mailserver`) in the Docker setup.
3. Create email service module `app/services/email.py` — Implement IMAP service to fetch unread emails from the local mail server's inbox using `imaplib` and SMTP service to send email replies using the local Postfix/SMTP service or `aiosmtplib` pointing to `localhost`.

**Phase 2: Email Processing API Route**
3. Create email processing API route in `app/api/email_routes.py` — Add POST endpoint `/api/email/process` that accepts email payload (sender, subject, body, channel_name) and returns processing status
4. Integrate with existing LangGraph pipeline — In the email processing route, construct the initial state and route through the async node functions (`router_node_async`, `extractor_node_async`, `store_node_async`, `retriever_node_async`, `answer_node_astream`) to handle the "save_memory" vs "answer_question" decision

**Phase 3: Background IMAP Polling Task**
5. Add background IMAP polling task in `main.py` — Create a background task that periodically polls the local IMAP inbox for `{ChannelName}@swai.getac.com.tw`, processes each email through the email processing logic, and marks emails as read or moves them to a processed folder

**Phase 4: Security & Error Handling**
6. Add validation and rate limiting to email endpoints — Ensure channel_name is validated against existing channels, add basic validation to prevent unauthorized channel access
7. Add error handling and logging — Implement retry logic for failed email sends or memory storage operations, log processing failures for debugging

**Phase 5: Docker & Mail Service Configuration Updates**
8. Update `.github/reference/gx10-petallia/.env` — Add mail service configuration variables (email channel identifier, default channel name mapping, sender email address, DNS/MX record configuration notes)
9. Update `.github/reference/gx10-petallia/compose.yml` — Add mail server services (e.g., Postfix for SMTP, Dovecot for IMAP, or a containerized mail server like `docker-mailserver`) and ensure the fukae service can communicate with the local mail server services.
10. Update `Dockerfile` or `compose.yml` — Include mail server dependencies or mail server container configurations to host the mail service (MTA and IMAP server).
11. Update `.github/reference/gx10-petallia/nginx/nginx.conf` or Docker network configuration — Ensure mail ports (25, 587, 465, 993, 143) are exposed and properly configured for incoming and outgoing mail, while keeping the web server (FastAPI) on port 7950.

**Relevant files**
- `app/core/config.py` — Add mail service configuration settings (local mail server host/port, email channel identifier, sender email address)
- `app/services/email.py` (new file) — Implement IMAP polling service from the local mail server and SMTP email sending service to the local mail server
- `app/api/email_routes.py` (new file) — Add email processing POST endpoint that integrates with the LangGraph pipeline
- `app/agent/graph.py` — Reference existing `secretary_graph` and async node functions for routing, extracting, storing, and answering
- `app/agent/node_async.py` — Reference `router_node_async`, `extractor_node_async`, `store_node_async`, `retriever_node_async`, `answer_node_astream` for pipeline execution
- `app/memory/store.py` — Reference `LanceStore` methods (`add_memory`, `import_chunks`, `search_memory`) for memory operations
- `main.py` — Add background IMAP polling task and email processing lifecycle management
- `.github/reference/gx10-petallia/.env` — Add mail service configuration variables
- `.github/reference/gx10-petallia/compose.yml` — Add mail server services (Postfix/Dovecot or containerized mail server) and configure network communication
- `Dockerfile` or mail server configuration files — Set up local mail service hosting (MTA and IMAP server)

**Verification**
1. Verify mail server services (Postfix/Dovecot or containerized mail server) are running and listening on the correct ports (25, 587, 465, 993, 143).
2. Test IMAP connection by running a script that connects to the local IMAP server and lists unread emails for the configured inbox (`{ChannelName}@swai.getac.com.tw`).
3. Test SMTP connection by running a script that sends a test email using the local SMTP service (Postfix).
4. Test the email processing endpoint by sending a POST request to `/api/email/process` with a mock email payload containing a question and verify the response includes the generated answer.
5. Test the email processing endpoint with a "save_memory" payload and verify the memory is stored in LanceDB by checking the `/api/channels/{channel_id}/memories` endpoint.
6. Test the background IMAP polling task by starting the server and verifying it polls the local inbox, processes emails, and marks them as read.

**Decisions**
- **Approach**: Host a local mail service (MTA like Postfix for SMTP, IMAP server like Dovecot) to receive and send emails by itself, rather than relying on external IMAP/SMTP servers. The server polls its own local IMAP inbox and sends replies via the local SMTP service.
- **Channel mapping**: Use the email address prefix (e.g., `support@swai.getac.com.tw` -> channel_id `support`) as the default channel identifier.
- **Security & DNS**: Configure MX records for `swai.getac.com.tw` to point to the server's public IP or domain. Ensure SPF, DKIM, and DMARC records are configured to prevent replies from being marked as spam by recipient email providers.
- **Includes**: Local mail server setup (Postfix/Dovecot or containerized mail server), IMAP polling, SMTP sending, LangGraph integration, LanceDB storage, plain text email processing, HTML email replies.
- **Excluded**: Advanced email parsing (attachments, complex HTML formatting) — starts with plain text body only.

**Further Considerations**
1. **Email parsing**: Should the system support HTML emails and attachments?
   - Option A: Strip HTML and ignore attachments for now (faster MVP)
   - Option B: Add HTML-to-text conversion and attachment extraction using libraries like `beautifulsoup4` or `email.message.EmailMessage`
Ans: Strip HTML but replying email use html format.
     for the attachments, if the mail content should save to memory, send attachments to indexer and store to the memory.

2. **Channel identification**: How to determine the channel from the email address or content?
   - Option A: Use the prefix before `@swai.getac.com.tw` as the channel_id (e.g., `support@swai.getac.com.tw` -> `support`)
   - Option B: Require a specific subject line prefix or email header to identify the channel

Ans: Option A, but if no channel is found, reply to the sender indicating that there's no corresponding channel.

3. **Email authentication & DNS**:
   - Configure MX (Mail Exchange) records in DNS for `swai.getac.com.tw` to point to the server's public IP or domain to receive incoming mail from the internet.
   - Ensure SPF, DKIM, and DMARC records are configured for `swai.getac.com.tw` to prevent outgoing replies from being marked as spam by recipient email providers.
   - Be aware that running a self-hosted mail server requires proper reverse DNS (rDNS/PTR) configuration for the server's public IP to ensure good deliverability.

4. **Docker & Mail Service configuration**:
   - Update `compose.yml` to include mail server services (e.g., Postfix for SMTP, Dovecot for IMAP, or a containerized mail server solution like `docker-mailserver`).
   Ans: use `docker-mailserver` for the mail server setup.
   - Expose and configure mail ports (25 for incoming SMTP, 587/465 for SMTP submission, 993/143 for IMAP) in the Docker network or host configuration.
   - The FastAPI web server continues to listen on port 7950 for HTTP/HTTPS requests.
