# followroll

See what the people you follow on GitHub are writing.
**[See a live one](https://ki-seki.github.io/followroll/)**

<img src=".github/screenshot.png" alt="The page in a browser window and on a phone: a timeline of posts, with the people who wrote them alongside">

<sub>The screenshot shows made-up sample data.</sub>

It finds the blogs of the people you follow on its own and lists their latest
posts, with a Discover tab for blogs one step further out. You can repost, and
you see what the people you follow repost. Nobody signs up and there is no
server: it runs on GitHub Actions and GitHub Pages.

## Get your own

**[Follow the five steps](https://ki-seki.github.io/followroll/#how-do-i-make-my-own)**:
fork, then four presses on GitHub, each shown with a picture. Your page
appears at `https://<you>.github.io/followroll/`.

- Keep the repository's name: pages find each other by it.
- To repost, turn on **Discussions** in your repository's settings.
- To have posts translated between Chinese and English, add a
  [DeepSeek](https://platform.deepseek.com) key as a repository secret named
  `DEEPSEEK_API_KEY`.
- When a new [release](https://github.com/Ki-Seki/followroll/releases) is
  out, a dot appears on the settings icon of your page: on GitHub, press
  **Sync fork**, then **Update branch**.
