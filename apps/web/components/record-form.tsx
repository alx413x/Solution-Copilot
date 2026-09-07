"use client";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useState } from "react";
const schema = z.object({
  name: z.string().trim().min(1, "请填写名称").max(200, "名称最多 200 字"),
  industry: z.string().max(120),
  region: z.string().max(120),
  company_size: z.string().max(80),
  description: z.string().max(10000),
});
export type Fields = z.infer<typeof schema>;
export function RecordForm({
  kind,
  initial = {},
  onSave,
  onCancel,
}: {
  kind: "customer" | "project";
  initial?: Partial<Fields>;
  onSave: (fields: Fields) => Promise<void>;
  onCancel: () => void;
}) {
  const [error, setError] = useState("");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<Fields>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: "",
      industry: "",
      region: "",
      company_size: "",
      description: "",
      ...initial,
    },
  });
  return (
    <form
      className="record-form"
      onSubmit={handleSubmit(async (values) => {
        setError("");
        try {
          await onSave(values);
        } catch (e) {
          setError(e instanceof Error ? e.message : "保存失败");
        }
      })}
    >
      <label>
        名称
        <input
          autoFocus
          {...register("name")}
          maxLength={200}
          aria-invalid={!!errors.name}
        />
      </label>
      {errors.name && (
        <p role="alert" className="error">
          {errors.name.message}
        </p>
      )}
      {kind === "customer" ? (
        <div className="fields">
          <label>
            行业
            <input {...register("industry")} maxLength={120} />
          </label>
          <label>
            地区
            <input {...register("region")} maxLength={120} />
          </label>
          <label>
            企业规模
            <input {...register("company_size")} maxLength={80} />
          </label>
        </div>
      ) : (
        <label>
          项目简介
          <textarea {...register("description")} maxLength={10000} rows={4} />
        </label>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <div className="actions">
        <button className="primary" disabled={isSubmitting}>
          {isSubmitting ? "保存中…" : "保存"}
        </button>
        <button type="button" onClick={onCancel} disabled={isSubmitting}>
          取消
        </button>
      </div>
    </form>
  );
}
