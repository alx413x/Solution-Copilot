import { Knowledge } from "../../../../../components/knowledge";
export default async function Page({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <Knowledge scope="project" id={projectId} />;
}
