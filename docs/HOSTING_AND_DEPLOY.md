# Hosting and Deploying the Judgment Diary

Written for someone who does not code. Prices are approximate and should be checked on the provider's website before you sign up. This is a recommendation; it depends on the open question in `docs/DESIGN.md` about the combined app. If the combined app already has a host, use that host.

## 1. Recommendation in one paragraph

Use **Render** with two paid services: one **Web Service** (the website) and one **managed PostgreSQL database** (where your notes live). Expect about **US$15 a month** in total (roughly $7 for the web service and $7 to $8 for the smallest paid database; confirm on Render's pricing page). **Railway** is a reasonable alternative with similar cost and similar steps.

## 2. Why paid, and what to avoid

- **Avoid free databases.** Free databases on most hosts are deleted or paused after a short time. Your life's work cannot sit on that.
- **Avoid free web services.** They go to sleep when unused and take a long time to wake, which is annoying and can look like a failure.
- **Never store data on the server's disk.** On these hosts, the disk is wiped at every update. Everything goes into the database. The app is built this way (and the design forbids files on disk).
- Your data (about 950 Items) is tiny. The cheapest paid tiers are plenty. You pay for **reliability**, not size.

## 3. Two layers of backup

Backups are your safety net, so there are two independent layers.

1. **The host's database backups.** Render's paid databases keep automatic backups and allow recovery to an earlier point in time (the length of time depends on the plan; check the plan page). This protects against host or database trouble.
2. **The app's own nightly backup.** Every night the app creates a full machine-readable backup file (all Subjects, Topics, Items, Notes, Trash, history and settings). It keeps **at least 30 days**. You can **download any of them** from the Backups screen in the app, and you can restore from one (with a preview first).
3. **Optional but recommended: an off-site copy.** The app can also send each nightly file to a separate storage service, such as **Backblaze B2** or **Cloudflare R2**. These cost pennies per month for this amount of data. Even if your host account is lost, you still have your data elsewhere.
4. **Your own habit:** download a backup to your computer once a month and keep it somewhere you control (for example a USB drive or your own cloud folder).

The Backups screen shows when the last backup ran and whether it worked. If a night's backup fails, the app shows a warning at the top of every page.

## 4. First-time setup outline (done once, with Kiro's help)

You will need: an email address, a payment card, and a GitHub account (the project already lives on GitHub).

1. **Create a Render account** at render.com using your email. Add a payment card.
2. **Connect Render to GitHub.** Render asks permission to see the Judgment Diary project. Give access to that project only.
3. **Create the database.** In Render choose New, then PostgreSQL. Pick a name, the region closest to you (for example Singapore or Mumbai if offered), and a **paid** plan. Do not choose Free.
4. **Create the web service.** Choose New, then Web Service, and pick the Judgment Diary project from GitHub. Kiro will tell you the settings to type in (they are listed in the project's setup note).
5. **Secrets.** Kiro will give you a few private settings (a secret key, the database address). You paste them into Render's Environment page. You never put them in GitHub.
6. **First start.** Render builds and starts the site, then gives you an address. Open it. You should see the login page.
7. **Create your Admin account.** Kiro will give you a one-time step to do this safely. Choose a long password, and store it in a password manager.
8. **Custom address (optional).** If you own a domain name, Render shows you where to point it. https (the padlock) is automatic.
9. **Switch on the nightly backup** in the app's Backups screen, and (optional) enter the details of the off-site storage.
10. **Do a restore rehearsal** on a practice copy before putting real data in: download a backup, restore it, and confirm it works. Only then is the system ready for the real Word import.

## 5. How to deploy a change (every time)

You do not touch code. The steps are:

1. **You ask Kiro** for the change in plain words.
2. **Kiro makes the change and opens a "pull request"** on GitHub. This is a request that says "please add this change". Nothing is live yet. Kiro explains what changed and how to check it.
3. **You look at it.** Where possible Kiro provides a test copy of the site (a preview) so you can try it first.
4. **You click the green Merge button** on the pull request page on GitHub. This is your approval. If you are not sure, do not click it; ask Kiro.
5. **Render notices and updates the live site automatically.** It takes a few minutes. Render shows "Live" when finished.
6. **Backup before a database change.** If a change alters how the data is stored (called a "migration"), the app automatically takes a backup first and Kiro will tell you in the pull request. Before you click Merge on those, confirm you see "Backup taken" in the app's Backups screen for today, or press "Backup now".
7. **Check the site.** Open it, and check the thing that changed. Look at a couple of familiar Subjects to be sure all is as before.
8. **If something is wrong, roll back.** In Render, open the web service, go to Events or Deploys, find the previous good deploy and press **Rollback** (or Redeploy on the earlier one). This restores the previous version of the program in a minute or two. It does not change the data. If the data was changed by a migration, tell Kiro and restore from the pre-change backup (with the preview) instead.

## 6. Everyday safety habits

- Keep the Admin password in a password manager. Use unique passwords for every user.
- Turn on two-step login on your Render and GitHub accounts.
- Never share your Render or GitHub login. Create separate accounts in the app for others, through Admin.
- Look at the Backups screen once a week: the date of the last backup should be recent.
- Keep a monthly download on your own computer (section 3).

## 7. Costs at a glance (approximate; verify before signing up)

| Item | About per month |
|---|---|
| Render Web Service (paid starter) | $7 |
| Render PostgreSQL (smallest paid) | $7 to $8 |
| Off-site backup storage (optional) | under $1 |
| Domain name (optional) | $1 to $2 (billed yearly) |
| **Total** | **about $15 to $18** |

## 8. If you want to change hosts later

Because everything is in the database and the app can export a complete machine-readable backup, moving to another host (Railway or any other) means: set up the new host, restore the latest backup file there, check, then point the address across. Your data is never trapped.
