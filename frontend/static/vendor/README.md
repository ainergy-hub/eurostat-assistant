# Vendored browser assets

The app serves these third-party files itself so that no request leaves the deployment's origin and
the Content-Security-Policy can restrict scripts, styles, and fonts to `'self'`.

| Path | Package | Version | License |
| --- | --- | --- | --- |
| `vega/vega.min.js` | [vega](https://www.npmjs.com/package/vega) | 6.2.0 | BSD-3-Clause |
| `vega/vega-lite.min.js` | [vega-lite](https://www.npmjs.com/package/vega-lite) | 6.4.3 | BSD-3-Clause |
| `vega/vega-embed.min.js` | [vega-embed](https://www.npmjs.com/package/vega-embed) | 7.1.0 | BSD-3-Clause |
| `vega/vega-interpreter.js` | [vega-interpreter](https://www.npmjs.com/package/vega-interpreter) | 2.3.2 | BSD-3-Clause |
| `fonts/*.woff2` | [@fontsource/ibm-plex-mono](https://www.npmjs.com/package/@fontsource/ibm-plex-mono), [@fontsource/ibm-plex-serif](https://www.npmjs.com/package/@fontsource/ibm-plex-serif) | 5.3.0 | SIL OFL 1.1 |

The three Vega bundles are the unmodified `build/*.min.js` files from npm and are byte-identical to
the jsDelivr copies the app used before. `vega-interpreter.js` wraps the package's ES module build in
a classic script that reads its `vega-util` imports from the `vega` global; the interpreter lets
charts render without `'unsafe-eval'`. `fonts/fonts.css` contains the Latin and Latin Extended
`@font-face` rules for the weights used by `styles.css`.

To upgrade, download the new versions with `npm pack <package>@<version>`, replace the files, keep
the license files next to them, update this table, and run `npm run test:smoke`. The smoke suite
renders a chart under the production CSP and fails on any console error or external request.
