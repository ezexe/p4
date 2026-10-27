// Assembles the prompt the acts widget sends: one Markdown message, written as direct instructions,
// that names every picked act in order, every act left unpicked, and how to report.
// Shared by the page (inlined by build_acts_widget.py) and the test (required by node).
function assemblePrompt(data, pickedIds, notes) {
  notes = notes || {};
  const picked = data.acts.filter((a) => pickedIds.includes(a.id));
  const unpicked = data.acts.filter((a) => !pickedIds.includes(a.id));
  if (!picked.length) return "";
  const n = picked.length;
  const L = [];
  L.push("## Picked acts");
  L.push("");
  L.push(
    `I picked ${n === 1 ? "one act" : n + " acts"} from your closing widget${data.title ? ` (“${data.title}”)` : ""}. ` +
    `Run ${n === 1 ? "it" : "them"} exactly as written below, in the order listed, and run nothing else from that closing. ` +
    "This message is my word for these acts and only these."
  );
  if (data.repo || data.branch) {
    L.push("");
    L.push([data.repo && `Repository: \`${data.repo}\``, data.branch && `Branch: \`${data.branch}\``].filter(Boolean).join(" · "));
  }
  picked.forEach((a, i) => {
    L.push("");
    L.push(`### Act ${i + 1} of ${n}: ${a.title}`);
    L.push("");
    L.push(a.goal.trim());
    if (a.files && a.files.length) {
      L.push("");
      L.push("Work in these files:");
      a.files.forEach((f) => L.push(`- \`${f}\``));
    }
    if (a.constraints && a.constraints.length) {
      L.push("");
      L.push("Keep to these constraints:");
      a.constraints.forEach((c) => L.push(`- ${c}`));
    }
    if (a.done) {
      L.push("");
      L.push(`This act is done when ${a.done.trim().replace(/^[A-Z]/, (c) => c.toLowerCase()).replace(/\.$/, "")}.`);
    }
    const note = (notes[a.id] || "").trim();
    if (note) {
      L.push("");
      L.push(`My added context for this act: ${note}`);
    }
  });
  if (unpicked.length) {
    L.push("");
    L.push("### Not picked");
    L.push("");
    L.push("Leave these undone. Offer them again at the next closing if they are still pending:");
    unpicked.forEach((a) => L.push(`- ${a.title}`));
  }
  L.push("");
  L.push("### How to report");
  L.push("");
  L.push(
    "Open your reply with the Deviations block: one line for each place you departed from these acts as written, or `none`. " +
    "Then report each act in order: what you changed, the checks you ran and their results, and the commit hash if you committed. " +
    "If an act cannot be done as written, stop at that act, say what blocked it, and do not substitute a different act."
  );
  if (data.round) {
    // the reply records this pick into the session's acts page from this line: build_acts_widget.py pick
    L.push("");
    L.push(`<!-- acts-widget round=${data.round} picked=${picked.map((a) => a.id).join(",")} -->`);
  }
  return L.join("\n");
}
if (typeof module !== "undefined") module.exports = { assemblePrompt };
