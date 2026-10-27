# Third-party notices

This repository is under the MIT License ([LICENSE](LICENSE)), except for the parts below, which keep their own licenses.

## Vendored agent skills

These folders in `.agents/skills/` are copies of other projects' skills (restored with `npx skills experimental_install`, see `skills-lock.json`). Each is MIT licensed by its authors:

| Skills | Source | Copyright |
|---|---|---|
| `analytics`, `community-marketing`, `content-strategy`, `launch`, `social` | [coreyhaines31/marketingskills](https://github.com/coreyhaines31/marketingskills) | Copyright (c) 2025 Corey Haines |
| `find-skills` | [vercel-labs/skills](https://github.com/vercel-labs/skills) | Copyright (c) 2026 Vercel, Inc. |
| `ffmpeg` | [digitalsamba/claude-code-video-toolkit](https://github.com/digitalsamba/claude-code-video-toolkit) | Copyright (c) 2024 Digital Samba |
| `threejs-weather` | [mengto/skills](https://github.com/mengto/skills) | Copyright (c) 2026 Meng To |

For each of them, under its copyright line above:

> Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

## Assets

- [docs/asset-ledger.csv](docs/asset-ledger.csv) records the source and license of every external or generated asset. Third-party assets in the repo are CC0 and keep that license, for example the Shiba Inu model by Quaternius in `assets/models/`.
- Not in the repository: music (the Minecraft tracks belong to Mojang and are imported locally from the game), fonts (SIL Open Font License, downloaded into `cache/`), reference frames from other creators' videos, and model weights.

## Dependencies

three.js and Electron come from npm (`package.json`), the Python packages from PyPI (`requirements.lock.txt`), each under its own license. None of them is copied into this repository.
