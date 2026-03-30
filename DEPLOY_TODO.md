# Deploy To-Do List

After Cursor finishes the code changes, follow these steps to get the site live.

---

## A. Set up GitHub SSH key (if you don't already have one)

1. Check if you already have a key:
   ```bash
   ls ~/.ssh/id_ed25519.pub
   ```
2. If not, generate one:
   ```bash
   ssh-keygen -t ed25519 -C "your-email@example.com"
   ```
3. Copy the public key:
   ```bash
   pbcopy < ~/.ssh/id_ed25519.pub
   ```
4. Go to https://github.com/settings/keys and click "New SSH key", paste it

---

## B. Create GitHub repo and push

1. Go to https://github.com/new and create a repo (e.g., `historyfm`) — **do not** initialize with README/gitignore
2. Push the frontend:
   ```bash
   cd ~/NovelGen/frontend
   git add -A
   git commit -m "Initial commit with content"
   git remote add origin git@github.com:<your-username>/historyfm.git
   git branch -M main
   git push -u origin main
   ```

---

## C. Connect to Vercel

1. Go to https://vercel.com and sign in with your GitHub account
2. Click "Add New Project"
3. Import the `historyfm` repo
4. Leave all settings as default (Vercel auto-detects Next.js)
5. Click "Deploy"
6. You'll get a live URL like `https://historyfm.vercel.app` in about 60 seconds

---

## D. (Optional) Custom domain

1. Buy a domain from any registrar (Namecheap, Google Domains, Cloudflare, etc.)
2. In Vercel: Project Settings > Domains > Add your domain
3. Update DNS as Vercel instructs (usually a CNAME record pointing to `cname.vercel-dns.com`)

---

## Day-to-Day Workflow After Setup

**Generate a chapter:**
```bash
sovereign-ink next -p louisiana_purchase_phase11_v2_3ch
```

**Deploy to the live site:**
```bash
bash scripts/deploy.sh
```

**Add a brand new novel:**
1. Add an entry to the `novels:` list in `generation_config.yaml`
2. Generate chapters with the pipeline
3. Run `bash scripts/deploy.sh`
