import { RecordDetail } from "../../../../components/record-detail";
export default async function Page({
  params,
}: {
  params: Promise<{ customerId: string }>;
}) {
  const { customerId } = await params;
  return <RecordDetail kind="customers" id={customerId} />;
}
