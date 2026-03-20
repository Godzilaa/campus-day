const demo = document.getElementById("demo");

if (demo) {
  demo.addEventListener("mouseenter", () => {
    demo.style.transform = "translateY(-2px)";
  });

  demo.addEventListener("mouseleave", () => {
    demo.style.transform = "translateY(0)";
  });
}
