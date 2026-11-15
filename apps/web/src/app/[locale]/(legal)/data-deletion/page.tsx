import type { Metadata } from "next";
import { setRequestLocale } from "next-intl/server";
import { CONTACT_EMAIL, LegalDoc, type LegalText, OPERATOR } from "../legal-doc";

const EN: LegalText = {
  title: "Data Deletion",
  updated: "Effective 12 November 2026",
  intro: `How to remove the data Stravica Social (operated by ${OPERATOR}) holds about you or your business, including data received through Facebook and Instagram.`,
  sections: [
    { title: "Remove a connected Facebook or Instagram account", body: [
      "In Stravica Social open Settings → Accounts and choose Disconnect on the account. Its access tokens are deleted at once and no new data is received from it.",
      "You can also remove the app from Facebook: Settings & privacy → Settings → Apps and Websites → Social Stravica → Remove. This revokes our access at Meta.",
    ] },
    { title: "Delete your account and all workspace data", body: [
      `Send an e-mail to ${CONTACT_EMAIL} from the address of your account with the subject "Delete my data" and the name of your workspace.`,
      "We confirm the request, then erase your account, your workspaces, connected accounts, posts, media, inbox messages and comments within 30 days. Records we must keep by law (for example invoices) are kept only as long as required.",
    ] },
    { title: "You wrote to a business that uses Stravica Social", body: [
      `If you sent a message or comment to a Page or Instagram account managed with Stravica Social and want it removed from our systems, e-mail ${CONTACT_EMAIL} with the name of the Page or account and your public name or username. We will delete it within 30 days and inform the business.`,
    ] },
  ],
};

const AR: LegalText = {
  title: "حذف البيانات",
  updated: "سارية من 12 نوفمبر 2026",
  intro: `طريقة إزالة البيانات التي تحتفظ بها منصة Stravica Social (تُشغّلها ${OPERATOR}) عنك أو عن نشاطك التجاري، ومنها البيانات الواردة عبر فيسبوك وإنستغرام.`,
  sections: [
    { title: "إزالة حساب فيسبوك أو إنستغرام مربوط", body: [
      "في المنصة افتح الإعدادات ← الحسابات واختر «إلغاء الربط» للحساب. تُحذف رموز الوصول فوراً ولا تصلنا منه أي بيانات جديدة.",
      "ويمكنك أيضاً إزالة التطبيق من فيسبوك: الإعدادات والخصوصية ← الإعدادات ← التطبيقات ومواقع الويب ← Social Stravica ← إزالة، فيُلغى وصولنا لدى ميتا.",
    ] },
    { title: "حذف حسابك وكل بيانات مساحة العمل", body: [
      `أرسل بريداً إلى ${CONTACT_EMAIL} من بريد حسابك بعنوان «احذف بياناتي» مع اسم مساحة العمل.`,
      "نؤكد الطلب ثم نمسح حسابك ومساحات العمل والحسابات المربوطة والمنشورات والوسائط والرسائل والتعليقات خلال 30 يوماً. وما يُلزمنا القانون بالاحتفاظ به (مثل الفواتير) يُحفظ للمدة المطلوبة فقط.",
    ] },
    { title: "راسلتَ نشاطاً تجارياً يستخدم المنصة", body: [
      `إذا أرسلت رسالة أو تعليقاً لصفحة أو حساب إنستغرام يُدار عبر Stravica Social وتريد إزالته من أنظمتنا، راسلنا على ${CONTACT_EMAIL} مع اسم الصفحة أو الحساب واسمك العام أو اسم المستخدم، ونحذفه خلال 30 يوماً ونُبلغ النشاط التجاري.`,
    ] },
  ],
};

export const metadata: Metadata = { title: "Data Deletion" };

export default async function DataDeletionPage({ params }: { params: Promise<{ locale: string }> }) {
  const { locale } = await params;
  setRequestLocale(locale);
  return <LegalDoc doc={locale === "ar" ? AR : EN} />;
}
