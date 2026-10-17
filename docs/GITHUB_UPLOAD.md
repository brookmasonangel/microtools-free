# Put Micro Tools Free on GitHub

Use a fresh extraction of `MicroTools_Free_v0.1.0.zip` for your first upload. It contains the complete free toolkit, MIT licence, examples, local test evidence and GitHub test workflow.

1. Sign in and open [Create a repository](https://github.com/new).
2. Use your account as owner, name it `microtools-free`, and choose **Public**. Suggested description: `Seven free local tools for text, config, JSONL, logs, stream usage, retry timing and Batch files.` Leave GitHub's generated README, licence and .gitignore options off; those files are already supplied. Click **Create repository**.
3. On the empty repository page, click **uploading an existing file**. On a populated repository, use **Add file → Upload files**.
4. Open the extracted `microtools-free` directory. Drag its **contents** into the upload area, preserving subfolders. Upload the source files, not the ZIP or an extra outer folder. `README.md`, `LICENSE`, `microtools_free`, `tests` and `examples` should appear at the repository root. Include `.github`, `.gitignore` and `.gitattributes` from the fresh package.
5. Use commit message `Initial release of Micro Tools Free`, choose the repository's default branch for this initial upload, and complete the commit. The confirmation label can vary with branch settings.
6. Check that the README renders on the repository homepage. Open **Actions** and inspect the `Tests` workflow. It is configured for Windows/Ubuntu and three Python versions. Only completed runs establish that those checks passed on GitHub.

The fresh ZIP has fewer than 100 files, so it fits GitHub's browser batch limit. Upload before adding your own logs or datasets. The provided examples use fictional values. A browser upload is a manual file selection: `.gitignore` is not a substitute for choosing the intended files.

After the initial upload, share the repository URL. GitHub offers a ZIP download from its Code menu. Future improvements can use branches and pull requests; the workflow checks pushes and pull requests. No paid-product URL is invented in this release; add your actual sales page when available.

Official instructions checked on 2026-10-02:

- [Create a repository](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)
- [Upload existing files](https://docs.github.com/en/repositories/working-with-files/managing-files/adding-a-file-to-a-repository)
