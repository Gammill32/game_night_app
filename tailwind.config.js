/** Tailwind v3 config for the standalone CLI (scripts/build_css.sh, Dockerfile).
 *  Every file that can contain a class name must be listed in `content`,
 *  including class strings built in <script> blocks and static JS. */
module.exports = {
  content: ["./app/templates/**/*.html", "./app/static/js/**/*.js", "./app/**/*.py"],
  theme: {
    extend: {
      colors: {
        brand: { DEFAULT: "#dc2626", hover: "#b91c1c" },
      },
    },
  },
  plugins: [],
};
