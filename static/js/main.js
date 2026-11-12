/* =============================================
   CampusFind — Main JavaScript
   ============================================= */


/**
 * Toggle the mobile navigation menu.
 * Called when the hamburger icon (menu-toggle) is clicked.
 */
function toggleMenu() {
    var navLinks = document.querySelector('.nav-links');
    navLinks.classList.toggle('open');
}


/**
 * Close the mobile menu when a nav link is clicked.
 * This gives a smooth experience — user taps a link,
 * the menu closes, and the page scrolls to the section.
 */
document.addEventListener('DOMContentLoaded', function () {

    var navLinks = document.querySelectorAll('.nav-links a');

    navLinks.forEach(function (link) {
        link.addEventListener('click', function () {
            var menu = document.querySelector('.nav-links');
            menu.classList.remove('open');
        });
    });

});

