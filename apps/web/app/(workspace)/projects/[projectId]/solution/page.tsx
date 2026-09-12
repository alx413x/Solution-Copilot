import { SolutionWorkspace } from "../../../../../components/solution";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ workflow?: string }>;
}) {
  const { projectId } = await params;
  const { workflow } = await searchParams;
  return <SolutionWorkspace projectId={projectId} workflowRunId={workflow} />;
}
