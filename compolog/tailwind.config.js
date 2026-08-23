/** Tailwind configuration for the compiled build (see README).
 *  The content globs must cover every template, otherwise the utility classes
 *  used there get purged out of the generated CSS. */
module.exports = {
  content: ["./app/web/templates/**/*.html"],
  theme: { extend: {} },
  plugins: [],
};
