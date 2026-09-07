import { RecordDetail } from "../../../../../components/record-detail";
export default async function Page({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <RecordDetail kind="projects" id={projectId} />;
}
