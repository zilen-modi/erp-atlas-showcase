"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowIcon, CloseIcon, KIND_ICON, SearchIcon } from "@/components/Icons";

type Item = { group: string; label: string; sub?: string; href: string };

const enc = encodeURIComponent;
const TRY = ["LG.XFER.MAINT", "M4401", "TRANSFER<10>", "DATEREQD", "IOREADU"];
const GROUP_TITLE: Record<string, string> = {
  "By meaning": "By meaning", Field: "Fields", Program: "Programs", Screen: "Screens", Menu: "Menus", "DICT name": "DICT names",
};

function toItems(r: any, meaning: any[] = []): Item[] {
  const items: Item[] = [];
  // a described behaviour ("freight calculation") matches summaries; names match below
  for (const m of meaning.filter((x) => x.kind !== "fact").slice(0, 3))
    items.push({ group: "By meaning", label: m.start ? `${m.program}:${m.start}` : m.program, sub: m.title,
      href: m.start ? `/program/${enc(m.program)}/source?line=${m.start}` : `/program/${enc(m.program)}` });
  for (const f of r.fields ?? [])
    items.push({ group: "Field", label: `${f.file}<${f.attr}>`, sub: f.dict_names?.join(", ") || "not named in DICT",
      href: `/field/${enc(f.file)}/${f.attr}` });
  for (const p of r.programs ?? [])
    items.push({ group: "Program", label: p.name,
      sub: p.reached_launches ? `${Number(p.reached_launches).toLocaleString("en-US")} launches` : undefined,
      href: `/program/${enc(p.name)}` });
  for (const sc of (r.screens ?? []).slice(0, 4))
    items.push({ group: "Screen", label: sc.project, sub: `${sc.forms} form${sc.forms === 1 ? "" : "s"}${sc.program !== sc.project ? ` · ${sc.program}` : ""}`,
      href: `/screen/${enc(sc.project)}` });
  for (const m of r.menus ?? [])
    items.push({ group: "Menu", label: m.code, sub: m.program ?? m.exec, href: `/menu/${enc(m.code)}` });
  for (const d of r.dict_names ?? [])
    items.push({ group: "DICT name", label: d.name, sub: `${d.pick_file}<${d.attr}>`, href: `/field/${enc(d.pick_file)}/${d.attr}` });
  return items;
}

// Bold the part of `text` that matches the query (case-insensitive).
export function Highlight({ text, q }: { text: string; q: string }) {
  const i = q ? text.toUpperCase().indexOf(q.toUpperCase()) : -1;
  if (i < 0) return <>{text}</>;
  return <>{text.slice(0, i)}<mark>{text.slice(i, i + q.length)}</mark>{text.slice(i + q.length)}</>;
}

export default function SearchBox() {
  const router = useRouter();
  const params = useSearchParams();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [items, setItems] = useState<Item[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const [loading, setLoading] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const wrap = useRef<HTMLFormElement>(null);

  // "/" or Cmd/Ctrl+K focuses search from anywhere
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = document.activeElement?.tagName;
      const typing = tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
      if ((e.key === "/" && !typing) || ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k")) {
        e.preventDefault();
        input.current?.focus();
        input.current?.select();
      }
    };
    const onClick = (e: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    window.addEventListener("mousedown", onClick);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("mousedown", onClick);
    };
  }, []);

  // debounced suggestions
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setItems([]);
      return;
    }
    const ctl = new AbortController();
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const described = /\s/.test(term);       // words, not a name: also search by meaning
        const [r, m] = await Promise.all([
          fetch(`/api/search?q=${enc(term)}&limit=6`, { signal: ctl.signal }),
          described ? fetch(`/api/meaning?q=${enc(term)}&limit=3`, { signal: ctl.signal }).catch(() => null) : null,
        ]);
        if (r.ok) {
          const meaning = m?.ok ? (await m.json()).results ?? [] : [];
          setItems(toItems(await r.json(), meaning));
          setActive(-1);
        }
      } catch {
        /* aborted, or API down: keep previous suggestions */
      } finally {
        setLoading(false);
      }
    }, 140);
    return () => {
      clearTimeout(t);
      ctl.abort();
    };
  }, [q]);

  // keep the selected row visible by scrolling the list only (scrollIntoView would move the page too)
  useEffect(() => {
    const row = document.getElementById(`sg-${active}`);
    const list = document.getElementById("search-suggestions");
    if (!row || !list) return;
    const top = row.offsetTop, bottom = top + row.offsetHeight;
    if (top < list.scrollTop) list.scrollTop = top - 30;
    else if (bottom > list.scrollTop + list.clientHeight - 40) list.scrollTop = bottom - list.clientHeight + 40;
  }, [active]);

  function go(href: string) {
    setOpen(false);
    input.current?.blur();
    router.push(href);
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.min(items.length - 1, a + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(-1, a - 1));
    } else if (e.key === "Escape") {
      if (open) setOpen(false);
      else input.current?.blur();
    }
  }

  const term = q.trim();
  const showList = open && term.length !== 1;
  let lastGroup = "";

  return (
    <form
      ref={wrap}
      className={`searchbar ${showList ? "is-open" : ""}`}
      role="search"
      onSubmit={(e) => {
        e.preventDefault();
        if (active >= 0 && items[active]) go(items[active].href);
        else if (term) go(`/search?q=${enc(term)}`);
      }}
    >
      <SearchIcon className="sb-icon" />
      <input
        ref={input}
        value={q}
        onChange={(e) => { setQ(e.target.value); setOpen(true); }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder="Search programs, menus, fields…"
        aria-label="Search Atlas"
        aria-autocomplete="list"
        aria-expanded={showList}
        role="combobox"
        aria-controls="search-suggestions"
        autoComplete="off"
        spellCheck={false}
      />
      {q ? (
        <button type="button" className="sb-clear" aria-label="Clear search"
          onClick={() => { setQ(""); setItems([]); input.current?.focus(); }}>
          <CloseIcon size={14} />
        </button>
      ) : (
        <kbd className="sb-kbd" title="Press / or ⌘K to search">/</kbd>
      )}

      {showList && (
        <div className="suggest" id="search-suggestions" role="listbox">
          {term.length === 0 && (
            <>
              <div className="suggest-group">Try</div>
              <div className="chips" style={{ padding: "2px 12px 10px" }}>
                {TRY.map((t) => (
                  <button key={t} type="button" className="chip mono"
                    onMouseDown={(e) => { e.preventDefault(); setQ(t); }}>{t}</button>
                ))}
              </div>
            </>
          )}
          {term.length >= 2 && items.length === 0 && (
            <div className="suggest-empty">
              {loading ? "Searching…" : <>No names match. Press <kbd>Enter</kbd> to look inside the code as well.</>}
            </div>
          )}
          {items.map((it, i) => {
            const head = it.group !== lastGroup ? GROUP_TITLE[it.group] ?? it.group : null;
            lastGroup = it.group;
            const Icon = KIND_ICON[it.group];
            return (
              <div key={`${it.group}-${it.label}-${i}`}>
                {head && <div className="suggest-group">{head}</div>}
                <div
                  id={`sg-${i}`}
                  role="option"
                  aria-selected={i === active}
                  className={`suggest-item ${i === active ? "active" : ""}`}
                  onMouseEnter={() => setActive(i)}
                  onMouseDown={(e) => { e.preventDefault(); go(it.href); }}
                >
                  <span className="suggest-ico">{Icon && <Icon size={15} />}</span>
                  <span className={`suggest-label ${it.group === "Fact" ? "" : "mono"}`}><Highlight text={it.label} q={term} /></span>
                  {it.sub && <span className="suggest-sub"><Highlight text={it.sub} q={term} /></span>}
                </div>
              </div>
            );
          })}
          {term.length >= 2 && (
            <div className="suggest-item suggest-all" onMouseDown={(e) => { e.preventDefault(); go(`/search?q=${enc(term)}`); }}>
              <span>All results for “{term}”, including the code</span>
              <ArrowIcon size={14} />
            </div>
          )}
          <div className="suggest-foot">
            <span><kbd>↑</kbd> <kbd>↓</kbd> move</span>
            <span><kbd>Enter</kbd> open</span>
            <span><kbd>Esc</kbd> close</span>
          </div>
        </div>
      )}
    </form>
  );
}
