/** Renders one legal document: a title, the effective date and its sections. */
export type LegalSection = { title: string; body: string[] };
export type LegalText = { title: string; updated: string; intro: string; sections: LegalSection[] };

export const OPERATOR = "Stravica";
export const CONTACT_EMAIL = "n_auf5555@hotmail.com";

export function LegalDoc({ doc }: { doc: LegalText }) {
  return (
    <article className="space-y-6 leading-7">
      <header className="space-y-2 border-b border-black/10 pb-6">
        <h1 className="text-3xl font-bold">{doc.title}</h1>
        <p className="text-sm text-text-2">{doc.updated}</p>
        <p>{doc.intro}</p>
      </header>
      {doc.sections.map((section) => (
        <section key={section.title} className="space-y-2">
          <h2 className="text-xl font-semibold">{section.title}</h2>
          {section.body.map((paragraph) => (
            <p key={paragraph} className="text-[15px] text-[#333]">{paragraph}</p>
          ))}
        </section>
      ))}
      <p className="text-[15px]">
        <a className="font-semibold underline" href={`mailto:${CONTACT_EMAIL}`} dir="ltr">{CONTACT_EMAIL}</a>
      </p>
    </article>
  );
}
