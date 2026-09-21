import { Suspense } from "react";

import { PharmaApp } from "@/components/pharma/app";
import { Loading } from "@/components/pharma/ui";

export default async function PharmaPage({
  params,
}: {
  params: Promise<{ path?: string[] }>;
}) {
  const { path = [] } = await params;
  return (
    <Suspense fallback={<Loading />}>
      <PharmaApp path={path} />
    </Suspense>
  );
}
