# followroll

See what the people you follow on GitHub are writing.
**[See a live one](https://ki-seki.github.io/followroll/)**

<img src=".github/screenshot.png" alt="The page in a browser window and on a phone: a timeline of posts, with the people who wrote them alongside">

<sub>The screenshot shows made-up sample data.</sub>

It reads who you follow, finds their blogs on its own, and lists their latest
posts. A Discover tab shows blogs one step further out: people followed by the
people you follow. You can repost what you like, and the reposts of people
you follow show up in your timeline. Nobody has to sign up, and there is no
server: it runs on GitHub Actions and GitHub Pages.

## Get your own

1. **Fork** this repository.
2. Open the **Actions** tab of your fork and enable workflows.
3. Open **Settings → Pages** and set **Source** to **GitHub Actions**.
4. In **Actions**, open the **Following** workflow. If GitHub says its
   schedule is disabled in forks, press **Enable workflow**. Then press
   **Run workflow**.

Your page appears at `https://<you>.github.io/followroll/` and refreshes every
six hours. When a new [release](https://github.com/Ki-Seki/followroll/releases)
is out, a dot appears beside **followroll** at the top of your page: press
**Sync fork** on your repository to get it.

Keep the repository's name: followroll pages find each other by it. To repost,
also turn on **Discussions** under **Settings → General**: a repost is saved
as a discussion in your own repository.
