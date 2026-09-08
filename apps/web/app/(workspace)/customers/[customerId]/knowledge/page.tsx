import { Knowledge } from "../../../../../components/knowledge";
export default async function Page({
  params,
}: {
  params: Promise<{ customerId: string }>;
}) {
  const { customerId } = await params;
  return <Knowledge scope="customer" id={customerId} />;
}
