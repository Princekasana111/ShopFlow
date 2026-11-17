// Tiny, safe renderer for the assistant's replies: paragraphs, "- " bullet lists and **bold**.
// Builds React elements (no innerHTML), so model output can never inject markup.
function inline(text, keyPrefix) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
    part.startsWith("**") && part.endsWith("**") ? <strong key={`${keyPrefix}-${i}`}>{part.slice(2, -2)}</strong> : part,
  );
}

export default function Markdown({ text }) {
  const blocks = [];
  let list = null;
  text.split("\n").forEach((line, i) => {
    const bullet = line.match(/^\s*[-*•]\s+(.*)$/);
    if (bullet) {
      if (!list) {
        list = [];
        blocks.push({ type: "ul", items: list, key: i });
      }
      list.push(inline(bullet[1], `li${i}`));
    } else {
      list = null;
      if (line.trim()) blocks.push({ type: "p", content: inline(line, `p${i}`), key: i });
    }
  });
  return blocks.map((b) =>
    b.type === "ul" ? (
      <ul key={b.key}>{b.items.map((item, j) => <li key={j}>{item}</li>)}</ul>
    ) : (
      <p key={b.key}>{b.content}</p>
    ),
  );
}
