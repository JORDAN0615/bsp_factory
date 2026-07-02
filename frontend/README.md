# BSP Agent Console

React + Vite frontend for reviewing BSP Agent runs waiting at `human_review`.

## Development

```bash
cd frontend
npm install
npm run dev
```

Set the backend URL with:

```bash
cp .env.example .env
```

Default:

```env
VITE_API_BASE=http://localhost:8080
```

## Build

```bash
cd frontend
npm run build
```

The Dockerfile builds the Vite app and serves the static bundle with nginx using SPA
fallback routing.
