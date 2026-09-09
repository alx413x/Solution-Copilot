import { Requirements } from "../../../../../components/requirements";
export default async function Page({
  params,
}: {
  params: Promise<{ projectId: string }>;
}) {
  const { projectId } = await params;
  return <Requirements projectId={projectId} />;
}
