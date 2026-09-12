"use client";
import { useEffect, useRef, useState } from "react";
import { EditorContent, useEditor } from "@tiptap/react";
import { TableKit } from "@tiptap/extension-table";
import StarterKit from "@tiptap/starter-kit";
import type { components } from "../../../packages/contracts/api";
import { api } from "../lib/client";

type Section = components["schemas"]["SectionView"];
export function SolutionEditor({
  solutionId,
  section,
  version,
  writable,
  onDirty,
  refresh,
}: {
  solutionId: string;
  section: Section;
  version: number;
  writable: boolean;
  onDirty: (dirty: boolean) => void;
  refresh: () => Promise<unknown>;
}) {
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const base = useRef(version);
  const pending = useRef<{ content: string; id: string } | null>(null);
  const editor = useEditor({
    extensions: [
      TableKit.configure({ table: { resizable: false } }),
      StarterKit.configure({
        heading: { levels: [2, 3] },
        link: false,
        underline: false,
      }),
    ],
    content: section.content,
    immediatelyRender: false,
    editable: writable,
    editorProps: {
      attributes: {
        role: "textbox",
        "aria-label": "章节正文",
        "aria-multiline": "true",
      },
    },
    onUpdate: () => {
      setDirty(true);
      onDirty(true);
    },
  });
  useEffect(() => {
    editor?.setEditable(writable, false);
  }, [editor, writable]);
  useEffect(() => {
    if (editor && !dirty) {
      editor.commands.setContent(section.content, { emitUpdate: false });
      base.current = version;
    }
  }, [editor, section.content, version, dirty]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => {
      e.preventDefault();
    };
    const leave = (event: MouseEvent) => {
      const link =
        event.target instanceof Element ? event.target.closest("a") : null;
      if (
        link?.href &&
        link.target !== "_blank" &&
        !event.metaKey &&
        !event.ctrlKey &&
        !window.confirm("有未保存修改，确认离开？")
      ) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener("beforeunload", warn);
    document.addEventListener("click", leave, true);
    return () => {
      window.removeEventListener("beforeunload", warn);
      document.removeEventListener("click", leave, true);
    };
  }, [dirty]);
  async function save() {
    if (!editor) return;
    setBusy(true);
    setError("");
    const content = editor.getJSON();
    const serial = JSON.stringify(content);
    if (pending.current?.content !== serial)
      pending.current = { content: serial, id: crypto.randomUUID() };
    try {
      await api(`/api/backend/solutions/${solutionId}`, "PATCH", {
        version: base.current,
        section_id: section.id,
        request_id: pending.current.id,
        content,
        change_summary: `人工编辑：${section.title}`.slice(0, 240),
      });
      await refresh();
      pending.current = null;
      setDirty(false);
      onDirty(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel solution-editor">
      <h2>{section.title}</h2>
      {section.goal && <p className="muted">{section.goal}</p>}
      {section.warnings.map((warning, i) => (
        <p key={i} className="notice">
          {warning}
        </p>
      ))}
      {error && (
        <p role="alert" className="error">
          {error} 当前修改仍保留在编辑器。
        </p>
      )}
      {dirty && (
        <p role="status">
          有未保存修改（基于版本 {base.current}）。保存后再切换章节或历史版本。
        </p>
      )}
      {writable && (
        <div className="actions" role="toolbar" aria-label="正文格式">
          <button
            disabled={!editor || busy}
            onClick={() => editor?.chain().focus().toggleBold().run()}
          >
            粗体
          </button>
          <button
            disabled={!editor || busy}
            onClick={() => editor?.chain().focus().toggleItalic().run()}
          >
            斜体
          </button>
          <button
            disabled={!editor || busy}
            onClick={() =>
              editor?.chain().focus().toggleHeading({ level: 2 }).run()
            }
          >
            小标题
          </button>
          <button
            disabled={!editor || busy}
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
          >
            列表
          </button>
          <button
            disabled={!editor || busy}
            onClick={() =>
              editor
                ?.chain()
                .focus()
                .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
                .run()
            }
          >
            插入表格
          </button>
          <button
            disabled={!editor || busy || !editor.isActive("table")}
            onClick={() => editor?.chain().focus().addRowAfter().run()}
          >
            添加行
          </button>
          <button
            disabled={!editor || busy || !editor.isActive("table")}
            onClick={() => editor?.chain().focus().deleteTable().run()}
          >
            删除表格
          </button>
          <button
            disabled={!editor || busy}
            onClick={() => editor?.chain().focus().undo().run()}
          >
            撤销
          </button>
        </div>
      )}
      {!editor && <p role="status">正在加载编辑器…</p>}
      <EditorContent editor={editor} />
      {dirty && (
        <button
          disabled={busy}
          onClick={() => {
            if (window.confirm("放弃未保存修改并载入当前版本？")) {
              setDirty(false);
              onDirty(false);
              setError("");
              pending.current = null;
            }
          }}
        >
          放弃修改并载入当前版本
        </button>
      )}
      {writable && (
        <button
          className="primary"
          disabled={!dirty || busy}
          onClick={() => void save()}
        >
          {busy ? "正在保存…" : "保存新版本"}
        </button>
      )}
    </section>
  );
}
