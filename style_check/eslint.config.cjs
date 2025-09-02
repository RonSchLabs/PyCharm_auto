// noinspection JSUnresolvedVariable
/** @type {import("eslint").Linter.FlatConfig[]} */

// CJS-Import + Destrukturierung, damit PyCharm die Form erkennt
const { configs: { recommended } } = require("@eslint/js");

module.exports = [
  // 1) Ignorierliste (verhindert z. B. Self-Linting der *.cjs-Dateien)
  {
    ignores: ["**/*.cjs", "node_modules/**", ".venv/**", "style_check/**"]
  },

  // 2) Empfohlenes JS-Preset als EIN Flat-Config-Objekt
  recommended,

  // 3) Deine Projektregeln (weiteres Flat-Config-Objekt)
  {
    rules: {
      "no-unused-vars": "warn",
      "no-undef": "error"
    }
  }
];