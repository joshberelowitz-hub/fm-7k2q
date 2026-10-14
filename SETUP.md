# Setting up the Fiscal Monitor (one-off, ~20–30 minutes)

You need a free personal GitHub account. Check you're comfortable with your firm's policy on
using a personal account from a work machine — you can do steps 1–6 from a home computer.
You'll need a computer (not a phone) for step 3.

## 1. Create a GitHub account
Go to https://github.com/signup and sign up with a personal email.

## 2. Create an empty repository
1. Click the **+** (top right) → **New repository**.
2. Repository name: something not obvious, e.g. `fm-7k2q`. This becomes part of the web address.
3. Choose **Public** (free GitHub Pages hosting requires it).
4. Leave all the "Initialize" boxes **unticked**. Click **Create repository**.

## 3. Upload the files
1. Unzip `fiscal-monitor.zip` on your computer.
2. On the new repository page, click the link **uploading an existing file**.
3. Open the unzipped folder, select **everything inside it** (files *and* the folders `manual`,
   `tests`, `.github`) and drag it into the upload box.
   - On a Mac, `.github` is hidden: press **Cmd + Shift + .** in Finder to show it.
4. Click **Commit changes**.
5. Check a folder called `.github` now appears in the file list. If it doesn't:
   **Add file → Create new file**, type the name `.github/workflows/daily.yml`, paste in the
   contents of that file from the zip, and click **Commit changes**.

## 4. Turn on GitHub Pages
**Settings** (tab at the top of the repository) → **Pages** (left menu) →
under *Build and deployment*, set **Source** to **GitHub Actions**.

## 5. Let the daily job save its data
**Settings** → **Actions** → **General** → scroll to *Workflow permissions* →
choose **Read and write permissions** → **Save**.

## 6. Run it for the first time
1. Click the **Actions** tab. If asked, click the green button to enable workflows.
2. Click **Daily refresh** (left) → **Run workflow** (right) → green **Run workflow**.
3. Wait 2–4 minutes for a green tick.
4. Click into the run: the **deploy** box shows your address,
   `https://YOUR-USERNAME.github.io/YOUR-REPO-NAME/`. Bookmark it at work.

After this it refreshes itself every weekday at 06:30 UTC.

## If something goes wrong
- **Red cross on the run:** click the red step, copy the error text, paste it to Claude.
- **Page loads but a section shows an error box, or "Data health" lists failed sources:**
  copy the error text and paste it to Claude.

## Editing assumptions
Click a file in the repository → pencil icon → edit → **Commit changes**.
- `config.py` — LTCMA g and r overrides, recession betas, stress calibrations, elasticities.
- `manual/politics.csv` — election dates and political constraint scores (starting values are placeholders).
Changes show up on the next run, or run it manually from the Actions tab.
