export function jumpToSection(pageNumber) {
  const pageElement = document.querySelector(`#page-${pageNumber}`);
  if (pageElement) {
    pageElement.scrollIntoView({ behavior: "smooth" });
    pageElement.classList.add("highlight");
    setTimeout(() => {
      pageElement.classList.remove("highlight");
    }, 1500);
  }
}
