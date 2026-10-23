/** Helpers for the website editor (task 2.9). */

/** The editor's groups of fields, in page order. */
export const SECTIONS: { title: string; keys: string[] }[] = [
  { title: "Top of the page", keys: ["site_title", "tagline"] },
  { title: "Welcome", keys: ["hero_heading", "hero_text"] },
  { title: "About", keys: ["about_heading", "about_text"] },
  { title: "Products", keys: ["products_heading", "products_text"] },
  { title: "Contact", keys: ["contact_heading", "contact_text"] },
  { title: "In Google", keys: ["seo_title", "seo_description"] },
];

/** "12 / 60" and whether it is too long. */
export function counter(value: string, limit: number): { text: string; over: boolean } {
  const length = value.length;
  return { text: `${length} / ${limit}`, over: length > limit };
}

/** Wait until typing pauses, then run once. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, ms: number) {
  let timer: number | undefined;
  const run = (...args: A) => {
    window.clearTimeout(timer);
    timer = window.setTimeout(() => fn(...args), ms);
  };
  run.cancel = () => window.clearTimeout(timer);
  return run;
}
