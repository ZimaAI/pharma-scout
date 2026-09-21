import Image from "next/image";

export function PharmaLogo() {
  return (
    <div className="ph-brand">
      <Image src="/pharma/brand/logo.svg" width={36} height={36} alt="" />
      <div>
        <strong>
          Pharma<span>Scount</span>
        </strong>
        <small>医药研发情报</small>
      </div>
    </div>
  );
}
