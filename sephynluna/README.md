# SephynLuna Perfumery Hub

A beautiful, mobile-first perfume ordering web app for **SephynLuna Perfumery Hub** by Maria Adewolu Sasa.

---

## Tech Stack

| Layer       | Technology                        |
|-------------|-----------------------------------|
| Frontend    | React 19 + Vite 8                 |
| Styling     | Tailwind CSS v4                   |
| Fonts       | Cormorant Garamond + Lato (Google Fonts) |
| Phase 2     | Firebase Firestore + Notifications |
| Deployment  | Netlify / Vercel (Phase 2)        |

---

## Running Locally

### 1. Install dependencies

```bash
cd sephynluna
npm install
```

### 2. Start the development server

```bash
npm run dev
```

Then open your browser and go to: **http://localhost:5173**

You'll see the order form live. Any changes you save will update automatically (hot reload).

### 3. Build for production

```bash
npm run build
```

This creates a `dist/` folder with your production-ready app.

---

## Project Structure

```
sephynluna/
├── index.html                  ← Entry HTML, loads Google Fonts
├── vite.config.js              ← Vite + Tailwind plugin config
├── src/
│   ├── main.jsx                ← React root mount
│   ├── App.jsx                 ← Page layout: header + form card
│   ├── index.css               ← Tailwind import + brand theme colours
│   └── components/
│       ├── OrderForm.jsx       ← Order form with validation
│       └── SuccessMessage.jsx  ← Confirmation shown after submission
└── public/
    └── favicon.svg
```

---

## Brand Identity

- **App Name:** SephynLuna Perfumery Hub
- **Owner:** Maria Adewolu Sasa
- **Colors:** Deep Purple (`#3B0764`) + Gold (`#D4AF37`)
- **Fonts:** Cormorant Garamond (headings) · Lato (body)
- **Tone:** Elegant, boutique, premium

---

## Order Form Fields

| Field                    | Required | Notes                          |
|--------------------------|----------|--------------------------------|
| Customer Full Name       | Yes      |                                |
| WhatsApp Number or Email | Yes      |                                |
| Perfume Type             | Yes      | Brand Perfume or Custom Blend  |
| Base Type                | Yes      | Oil Based or Alcohol Based     |
| Preferred Scent / Notes  | Yes      | Free text                      |
| Quantity                 | Yes      | Minimum 1                      |
| Additional Instructions  | No       | Packaging, delivery notes, etc.|

---

## Phases

| Phase | Status     | Description                              |
|-------|------------|------------------------------------------|
| 1     | Complete   | Project setup + order form UI            |
| 2     | Upcoming   | Firebase Firestore + owner notifications |
| 3     | Upcoming   | Deployment to Netlify/Vercel             |
