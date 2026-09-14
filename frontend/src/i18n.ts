import catalog from "../../harness/locales/cs.json";

const messages: Record<string, string> = catalog.messages;

/** English source messages double as stable translation keys. */
export function translate(text: string, language = "en"): string {
  return language === "cs" ? (messages[text] ?? text) : text;
}
