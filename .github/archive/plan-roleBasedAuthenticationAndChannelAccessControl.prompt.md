## Plan: Role-Based Authentication and Channel Access Control

**TL;DR** - Implement a role-based access control system where all channels default to open access for all Telegram users with viewer role, managers can set channels to closed mode for selected members only, an admin role can see and manage all channels, and permissions determine access to "save memory", memory browser, document import, and chat capabilities.

### Current State
- Authentication: Simple Telegram access code (no external API integration)
- Channel management: Basic channel creation/listing/deletion via LanceStore
- No role/permission system exists - all authenticated users have full access
- Agent graph has `save_memory` and `answer_question` routing
- No channel access mode (open/closed) exists

### Implementation Steps

#### Phase 1: Channel Access Mode Management
1. **Create Channel Access Mode Schema** (`app/bot/telegram_sessions.py`)
   - Add `channel_access_mode` column to channel state: `open` (default) or `closed`
   - Add `channel_admins` table: `chat_id` (global admin users)
   - Add `channel_managers` table: `channel_id`, `chat_id`
   - Add `channel_writers` table: `channel_id`, `chat_id`
   - Add `channel_viewers` table: `channel_id`, `chat_id`

2. **Update Authentication Flow** (`app/bot/auth.py`, `app/bot/handlers.py`)
   - Remove Shiratsuyu login process via Telegram
   - Telegram users can access open channels with viewer role by default
   - Update `@require_auth` decorator to validate Telegram authentication only
   - Load admin user IDs from `.env` variable `SHIRATSUYU_ADMIN_USER_IDS` (comma-separated list of user IDs from Shiratsuyu)

#### Phase 2: Channel Role Management
3. **Channel Access Mode API** (`app/api/routes.py`)
   - `GET /api/channels/{channel_id}/access-mode` - Get channel access mode (open/closed)
   - `PUT /api/channels/{channel_id}/access-mode` - Set channel access mode (open/closed) - manager or admin only

4. **Channel Role Management API** (`app/api/routes.py`)
   - `POST /api/channels/{channel_id}/writers` - Add writer to channel - manager or admin only
   - `DELETE /api/channels/{channel_id}/writers/{chat_id}` - Remove writer - manager or admin only
   - `POST /api/channels/{channel_id}/viewers` - Add viewer to channel - manager or admin only
   - `DELETE /api/channels/{channel_id}/viewers/{chat_id}` - Remove viewer - manager or admin only
   - `GET /api/channels/{channel_id}/roles` - Get all roles for a channel - manager, admin, or user with access
   - `GET /api/channels` - List all channels - admin only
   - `GET /api/channels/{channel_id}/memories` - List memories for channel - admin or user with access

5. **Channel Access Mode Handlers** (`app/bot/handlers.py`)
   - `/channel access open` - Set channel to open mode (all Telegram users can access with viewer role)
   - `/channel access closed` - Set channel to closed mode (only selected members can access)

6. **Channel Role Management Handlers** (`app/bot/handlers.py`)
   - `/channel writers` - List writers for current channel - manager, admin, or user with access
   - `/channel add-writer <chat_id>` - Add writer - manager or admin only
   - `/channel remove-writer <chat_id>` - Remove writer - manager or admin only
   - `/channel viewers` - List viewers for current channel - manager, admin, or user with access
   - `/channel add-viewer <chat_id>` - Add viewer - manager or admin only
   - `/channel remove-viewer <chat_id>` - Remove viewer - manager or admin only

7. **Admin Handlers** (`app/bot/handlers.py`)
   - `/admin channels` - List all channels - admin only
   - `/admin channel <channel_id>` - Get channel info and roles - admin only

#### Phase 3: Permission Enforcement in Agent Graph
7. **Create Permission Checker** (`app/agent/permissions.py`)
   - `is_admin(chat_id)` - Check if user is a global admin
   - `is_channel_open(channel_id)` - Check if channel is in open access mode
   - `has_writer_permission(chat_id, channel_id)` - Check if user has writer, manager, or admin role
   - `has_viewer_permission(chat_id, channel_id)` - Check if user has viewer, writer, manager, or admin role, or if channel is open
   - `get_user_role(chat_id, channel_id)` - Return user's role in channel (admin, manager, writer, viewer, or none)
   - `can_access_channel(chat_id, channel_id)` - Check if user can access the channel (open mode, selected member, or admin)

8. **Update Agent Graph Nodes** (`app/agent/graph.py`, `app/agent/nodes.py`)
   - Modify `router_node` to check permissions before allowing `save_memory` decision
   - If channel is open: all Telegram users have viewer role by default
   - If user has writer/manager/admin role: allow `save_memory` or `answer_question`
   - If user has viewer role: force `answer_question` decision only
   - Update `store_node` to verify writer/manager/admin permission before saving memories
   - Update `retriever_node` to verify viewer/writer/manager/admin permission

#### Phase 4: Memory Browser and Document Import Permissions
9. **Update API Routes for Permissions** (`app/api/routes.py`)
   - `GET /api/channels` - List all channels - admin only
   - `GET /api/channels/{channel_id}/memories` - Require viewer+ permission, admin role, or open channel access
   - `POST /api/channels/{channel_id}/memories/import` - Require writer+ permission or admin role
   - `PUT /api/channels/{channel_id}/memories/{memory_id}` - Require writer+ permission or admin role
   - `DELETE /api/channels/{channel_id}/memories/{memory_id}` - Require writer+ permission or admin role
   - `POST /api/channels/{channel_id}/import/documents` - Require writer+ permission or admin role
   - `POST /api/channels/{channel_id}/import/json` - Require writer+ permission or admin role

10. **Update Telegram Handlers for Permissions** (`app/bot/handlers.py`)
   - `/memory browser` - Require viewer+ permission, admin role, or open channel access
   - `/memory save` - Require writer+ permission or admin role
   - `/document import` - Require writer+ permission or admin role

#### Phase 5: Web Client Migration to Vue 3 + TypeScript
11. **Create Vue 3 + TypeScript Project** (`web/` directory)
    - Use Vite to scaffold a Vue 3 + TypeScript project: `npm create vite@latest web -- --template vue-ts`
    - Install dependencies: Vue Router, Pinia (state management), Axios (API client), Element Plus (UI components)
    - Configure Vite to proxy API requests to `http://localhost:7950/api`

12. **Update Web Client Architecture** (`web/src/`)
    - Create API service layer with Axios for all backend endpoints
    - Implement state management with Pinia for channels, sessions, memories, and user permissions
    - Create Vue components for:
      - Channel management (list, create, delete)
      - Chat interface with session sidebar
      - Memory browser with import/export functionality
      - Document import interface
      - Role management UI (for admins and managers)
    - Implement route guards based on user roles and channel access permissions

13. **Update FastAPI Static File Mount** (`main.py`)
    - Remove `app.mount("/", StaticFiles(directory="static", html=True), name="static")`
    - Update to serve built Vue frontend: `app.mount("/", StaticFiles(directory="web/dist", html=True), name="static")`

14. **Update Dockerfile**
    - Add Node.js base image stage for building Vue frontend
    - Install Node.js dependencies and build the Vue project
    - Copy built static files to the Python image's `web/dist` directory
    - Update FastAPI to serve the built Vue frontend

### Relevant Files to Modify

**New Files:**
- `app/agent/permissions.py` - Permission checking utilities
- `web/` - Vue 3 + TypeScript project directory (created via Vite)
- `web/package.json`, `web/tsconfig.json`, `web/vite.config.ts`, `web/src/main.ts`, etc. - Vue project configuration files

**Modified Files:**
- `app/bot/telegram_sessions.py` - Add channel access mode and role management tables and methods
- `app/bot/auth.py` - Update `@require_auth` decorator for Telegram authentication only
- `app/bot/handlers.py` - Remove Shiratsuyu login flow, add channel access mode and role management commands
- `app/api/routes.py` - Add channel access mode endpoints, role management endpoints, enforce permissions
- `app/agent/graph.py` - Update graph state to include user permissions and channel access mode
- `app/agent/nodes.py` - Enforce permissions in `router_node`, `store_node`, `retriever_node`
- `main.py` - Update static file mount to serve Vue frontend from `web/dist`
- `Dockerfile` - Add Node.js build stage for Vue frontend and update static file serving

### Verification

1. **Authentication Tests:**
   - Telegram users can access open channels with viewer role by default
   - Telegram users cannot access closed channels unless they are selected members
   - Managers can change channel access mode between open and closed
   - Admins can see and manage all channels regardless of access mode

2. **Role Management Tests:**
   - Admins can add/remove managers, writers, viewers for any channel
   - Managers can add/remove writers, viewers (not managers) for their channels
   - Writers/viewers cannot modify roles
   - Role assignments are persisted in database

3. **Permission Enforcement Tests:**
   - Open channel: All Telegram users have viewer role by default
   - Admin: Can see and manage all channels, trigger "save memory", access memory browser, import documents, chat
   - Manager/Writer: Can trigger "save memory", access memory browser, import documents, chat
   - Viewer: Can only chat with agent, use `answer_question` in retriever_node
   - Unauthorized users receive permission denied messages

4. **API Endpoint Tests:**
   - Admin can list all channels via `GET /api/channels`
   - All memory import/update/delete endpoints require writer+ permission or admin role
   - All memory read endpoints require viewer+ permission, admin role, or open channel access

5. **Web Client Tests:**
   - Vue frontend builds successfully with Vite
   - All API endpoints are accessible through the Vue frontend
   - Role-based UI components are displayed correctly based on user permissions
   - Docker image builds successfully with both Python backend and Vue frontend
   - Vue frontend is served correctly from FastAPI's static file mount

### Decisions

- **Authentication Method:** Telegram authentication only, no Shiratsuyu API login process
- **Channel Access Mode:** All channels default to open access for all Telegram users with viewer role
- **Role Hierarchy:** Admin > Manager > Writer > Viewer (Admin can manage all channels, Manager includes Writer permissions, Writer includes Viewer permissions)
- **Manager Capabilities:** Channel managers can only set channel writers and viewers, not managers
- **Admin Configuration:** Admin user IDs are set in `.env` variable `SHIRATSUYU_ADMIN_USER_IDS` (comma-separated list of user IDs from Shiratsuyu)
- **Closed Channel Access:** Managers can set channels to closed mode, where only selected members (managers/writers/viewers) or admins can access them
- **Database Schema:** Add channel access mode and role management tables to existing `sessions.db` SQLite database
- **Permission Enforcement:** Enforce at both API route level and agent graph node level for security
- **Web Client Architecture:** Vue 3 + TypeScript with Vite, Vue Router, Pinia, Axios, and Element Plus
- **Web Client Deployment:** Build Vue frontend during Docker image build and serve from FastAPI's static file mount

### Further Considerations

1. **Role Inheritance:** Should managers automatically get writer and viewer permissions, or are they separate?
Ans: Yes, managers should automatically inherit writer and viewer permissions to simplify role management and ensure consistent access control.
2. **Channel Access Mode Default:** Should new channels default to open or closed access mode?
Ans: New channels should default to open access mode to ensure ease of use and accessibility for all Telegram users.
3. **Viewer Role in Open Channels:** Should open channels grant viewer role automatically to all Telegram users, or require explicit addition?
Ans: Open channels should grant viewer role automatically to all Telegram users to streamline access and reduce administrative overhead.
4. **Admin User IDs Format:** Should `SHIRATSUYU_ADMIN_USER_IDS` use Shiratsuyu user IDs or Telegram chat IDs?
Ans: `SHIRATSUYU_ADMIN_USER_IDS` should use Shiratsuyu user IDs to maintain consistency with the existing admin configuration.
5. **Vue Project Structure:** Should the Vue project be in a separate repository or within the current project?
Ans: The Vue project should be in a `web/` directory within the current project to maintain a single deployment unit and simplify CI/CD.
6. **Docker Build Process:** How should the Vue frontend be built in the Dockerfile?
Ans: Use a multi-stage Docker build where the first stage builds the Vue frontend with Node.js, and the second stage copies the built static files to the Python image.
