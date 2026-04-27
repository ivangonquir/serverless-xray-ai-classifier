# LUNA Frontend

The clinician-facing web application for **LUNA (LUng kNowledge Assistant)**, a Clinical Decision Support System for early lung cancer screening.

## Status

- **Login** ✅ Wired to the real `auth_handler` Lambda (POST `/auth/login`).
- **Logout** ✅ Wired to `auth_handler` (POST `/auth/logout`).
- **Dashboard shell** ✅ Layout, sidebar, chat surface.
- **Chat** ⏳ Stubbed. The conversational LLM/RAG backend is not yet built; the chat shows a static greeting and a fake assistant echo for demo purposes. UI is final, behavior will be wired in once the backend exists.
- **Diagnostics** ⏳ Not yet integrated. The diagnostic backend (upload, SageMaker inference, WebSocket result push) is deployed but not yet called from the frontend.

## Stack

- **Next.js 14** (App Router, configured for static export)
- **React 18** + **TypeScript**
- **Tailwind CSS 3** with a custom LUNA design system
- Fonts: `Outfit` and `JetBrains Mono` (loaded from Google Fonts)

## Local development

### 1. Install dependencies

```bash
npm install
```

### 2. Configure environment variables

Copy the template and fill in the deployed API URLs (ask your backend teammate):

```bash
cp .env.local.example .env.local
# then edit .env.local
```

You need at minimum `NEXT_PUBLIC_API_URL` for login to work. `NEXT_PUBLIC_WS_URL` is reserved for future diagnostic features.

### 3. Run the dev server

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000). You'll be redirected to `/login`.

**Default credentials** (created by the backend `/auth/seed` endpoint):

| Username | Password    | Role   |
|----------|-------------|--------|
| `doctor` | `Luna2024!` | doctor |
| `admin`  | `Luna2024!` | admin  |

## Building for production

```bash
npm run build
```

Produces an `out/` folder of plain HTML/JS/CSS that can be uploaded to any static host. See **Deployment** below.

## Project structure

```
luna-frontend/
├── app/
│   ├── layout.tsx              Root layout: fonts, dark theme, metadata
│   ├── page.tsx                '/' - client-side router to /login or /dashboard
│   ├── globals.css             Tailwind directives + base styles
│   │
│   ├── login/page.tsx          '/login' - Clinician sign-in (REAL auth)
│   ├── dashboard/page.tsx      '/dashboard' - Chat surface (route-guarded)
│   │
│   └── components/
│       ├── LunaMark.tsx        Logo (SVG) and wordmark
│       ├── Sidebar.tsx         Collapsible left navigation + logout
│       └── ChatInterface.tsx   Messages + composer (currently stubbed)
│
├── lib/
│   └── auth.ts                 Login/logout/session helpers + apiFetch wrapper
│
├── .env.local.example          Template for environment variables
├── tailwind.config.js          Design tokens (palette, fonts, animations)
├── next.config.js              Configured for static export
├── tsconfig.json               TypeScript settings
└── package.json
```

## Authentication flow

1. User visits any page. If they aren't logged in, they're redirected to `/login`.
2. They submit `username` + `password`. Frontend calls `POST /auth/login`.
3. Backend verifies credentials against `UsersTable`, creates a 24-hour session token in `SessionsTable`, and returns it.
4. Frontend stores `{ token, userId, username, role }` in `localStorage` under the key `luna.session`.
5. Future authenticated calls go through `apiFetch()` in `lib/auth.ts`, which automatically attaches `Authorization: Bearer <token>`.
6. On logout, frontend calls `POST /auth/logout` to invalidate the token server-side, then clears `localStorage`.

## Mapping to functional requirements

| Requirement | Implementation |
|---|---|
| FR-1.1 Authentication | `app/login/page.tsx` + `lib/auth.ts` (real backend) |
| FR-1.2 Audit Logging | Handled server-side by `auth_authorizer` and each handler |
| FR-1.3 Traffic Management | Static frontend deployable to S3 + CloudFront |
| FR-UI 1.x Dashboard | `app/dashboard/page.tsx` (chat-centric per user journey) |
| FR-5.x LLM/RAG | Not yet implemented (chat stubbed) |
