// Settings > General: "Talk to LOKI from your phone" - pairing the Telegram bot (engine/channels.py).
// The token itself is a secret setting above this card (never shown again once saved); this card
// shows whether it works, which machine answers, makes the one-time pairing code (with a t.me link
// and its QR) and unpairs. Nothing here ever receives the token.
"use strict";

const Channels = (() => {
  let timer = 0;
  const qrCache = {};   // link -> svg, so the 5 s refresh does not fetch the QR again

  function node(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  function qrInto(holder, svg) {
    // engine/qr.py output: one <svg> built from our own text; parsed, never innerHTML'd raw.
    const doc = new DOMParser().parseFromString(String(svg || ""), "image/svg+xml");
    if (doc.documentElement && doc.documentElement.tagName.toLowerCase() === "svg") holder.append(document.importNode(doc.documentElement, true));
  }

  function lines(ch) {
    if (Array.isArray(ch.lines)) return ch.lines;   // a channel that writes its own (engine/channel_wechaty.py)
    const out = [];
    if (!ch.token_saved) {
      out.push("1. In Telegram, open @BotFather, send /newbot and pick a name.");
      out.push("2. Paste the token it gives you in \"Telegram bot token\" above.");
      out.push("3. Come back here and press Pair - then send the code to your bot.");
      return out;
    }
    out.push(ch.bot && ch.bot.username ? "Bot: @" + ch.bot.username : "Bot: not checked yet");
    out.push("This machine answers: " + (ch.poll_here ? "yes" : "no") + " - " + ch.poll_why);
    if (ch.poll_here) out.push(ch.polling ? "Listening for messages." : "Starting...");
    out.push(ch.paired ? "Paired with " + (ch.owner.name || "your Telegram") + ". Only that chat is answered." : "Not paired yet: nobody can use the bot.");
    out.push("Messages run in " + ch.mode + " mode; approvals and building stay on the computer.");
    return out;
  }

  async function draw(card) {
    if (!card.isConnected) { clearInterval(timer); return; }
    const data = await api("/channels").catch(() => null);
    const body = card.querySelector(".channel-body");
    body.replaceChildren();
    if (!data || !data.ok) { body.append(node("p", "note", "The engine is still starting.")); return; }
    for (const ch of data.channels || []) {
      for (const line of lines(ch)) body.append(node("p", "note", line));
      if (ch.last_error) body.append(node("p", "note error", ch.last_error));
      if (ch.pairing && ch.pairing.code) {
        const box = node("div", "pair-code");
        box.append(node("b", "", ch.pairing.code));
        const how = ch.pairing.link ? "Open the link (or scan it) on your phone, or send /start " + ch.pairing.code + " to the bot."
          : "Send /start " + ch.pairing.code + " to your bot in Telegram.";
        box.append(node("span", "", how + " Expires in " + Math.max(1, Math.round(ch.pairing.expires_in / 60)) + " min."));
        if (ch.pairing.link) {
          const a = node("button", "link", ch.pairing.link);
          a.type = "button";
          a.addEventListener("click", () => navigator.clipboard && navigator.clipboard.writeText(ch.pairing.link));
          a.title = "Copy the link";
          box.append(a);
          const holder = node("div", "qr-holder");
          box.append(holder);
          if (qrCache[ch.pairing.link]) qrInto(holder, qrCache[ch.pairing.link]);
          else api("/qr?text=" + encodeURIComponent(ch.pairing.link)).then((r) => {
            if (r && r.ok) { qrCache[ch.pairing.link] = r.svg; qrInto(holder, r.svg); }
          }).catch(() => {});
        }
        body.append(box);
      }
      const row = node("div", "channel-actions");
      if (ch.token_saved) {
        const pair = node("button", "", ch.paired ? "Pair again" : "Pair my phone");
        pair.type = "button";
        pair.addEventListener("click", async () => {
          const r = await api("/channels/pair", { channel: ch.name });
          if (!r.ok) addNotice(r.error || "Could not make a code.", true);
          draw(card);
        });
        const test = node("button", "quiet", "Check the bot");
        test.type = "button";
        test.addEventListener("click", async () => {
          const r = await api("/channels/test", { channel: ch.name });
          if (!r.ok) addNotice(r.error || "The bot did not answer.", true);
          draw(card);
        });
        row.append(pair, test);
        if (ch.paired) {
          const un = node("button", "quiet danger", "Unpair");
          un.type = "button";
          un.addEventListener("click", async () => { await api("/channels/unpair", { channel: ch.name }); draw(card); });
          row.append(un);
        }
      }
      body.append(row);
    }
  }

  function render(panel) {
    if (!panel) return;
    const old = panel.querySelector(".channel-card");
    if (old) old.remove();
    const card = node("div", "set-card channel-card");
    const text = node("div", "set-text");
    text.append(node("b", "", "Talk to LOKI from your phone (Telegram)"), node("small", "", "LOKI_TELEGRAM_TOKEN"));
    const body = node("div", "channel-body");
    card.append(text, body);
    const token = [...panel.querySelectorAll(".set-card")].find((c) => /LOKI_TELEGRAM_TOKEN$/.test((c.querySelector("small") || {}).textContent || ""));
    if (token) token.after(card); else panel.append(card);
    clearInterval(timer);
    draw(card);
    timer = setInterval(() => draw(card), 5000);   // shows "Paired" as soon as the phone sends the code
  }

  return { render };
})();
window.Channels = Channels;
