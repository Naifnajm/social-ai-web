"use client";
/** A production board: the full-screen flow canvas (it covers the app shell, like a design tool). */
import { useParams } from "next/navigation";
import { ProductionCanvas } from "@/components/production/production-canvas";

export default function ProductionBoardPage() {
  const params = useParams<{ id: string }>();
  const id = Number(params.id);
  return (
    <div className="fixed inset-0 z-50 bg-[#f2f2f4]">
      {Number.isFinite(id) && id > 0 && <ProductionCanvas boardId={id} />}
    </div>
  );
}
