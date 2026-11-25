# Shoonya REST API Guide

A working example of how to use the **Shoonya (Finvasia) OAuth REST API**, the new API Shoonya moved to in 2026. It covers logging in, searching for instruments, getting quotes, and streaming a live option chain over WebSocket.

## What's inside

- 🔑 **Automated OAuth login:** headless Chrome gets the auth code, swaps it for a session token, and caches the token for the day
- 🔎 **Instrument search** and **scrip master** download for NFO
- 💹 **Quotes** and a full **option chain** for any underlying
- 📡 **Live market data:** one Shoonya WebSocket connection shared with every browser that's connected
- 🖥️ **React frontend** that shows a live option chain table
- 📘 The official **OAuth REST API PDF** for reference

## How it's built

```
React frontend  ──REST + WebSocket──►  FastAPI gateway (:8000)  ──►  Shoonya REST + WebSocket
```

The backend is the only part that talks to Shoonya. The frontend never calls the broker directly.

The full walkthrough is in **[Shoonya_API/README.md](Shoonya_API/README.md)**. It covers the auth flow, the option chain pipeline and every endpoint.

## Tech stack

- **Backend:** Python, FastAPI, Selenium, WebSockets, pandas
- **Frontend:** React, TypeScript, Vite

## Run it locally

```bash
cd Shoonya_API/gateway_backend
pip install -r requirements.txt
cp .env.example .env        # add your Shoonya credentials
uvicorn server:app --reload

cd ../frontend
npm install && npm run dev
```

> ⚠️ Shoonya only allows login from the static IP address you registered in its portal.
