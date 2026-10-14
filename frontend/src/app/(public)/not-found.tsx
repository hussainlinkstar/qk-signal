import NotFoundContent from "@/components/NotFoundContent";

export default function PublicNotFound() {
  return (
    <NotFoundContent
      titleKey="notFound.public.title"
      descriptionKey="notFound.public.description"
      primaryHref="/"
      primaryLabelKey="notFound.public.primary"
    />
  );
}
