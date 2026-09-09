import { Dialogue } from "../../../../../components/dialogue";
export default async function Page({
  params,
  searchParams,
}: {
  params: Promise<{ projectId: string }>;
  searchParams: Promise<{ conversation?: string; after?: string }>;
}) {
  const { projectId } = await params;
  const query = await searchParams;
  const after = Number(query.after ?? 0);
  return (
    <Dialogue
      key={`${query.conversation}:${query.after}`}
      projectId={projectId}
      initialConversation={query.conversation}
      initialAfter={Number.isSafeInteger(after) && after >= 0 ? after : 0}
    />
  );
}
