/*---------------------------------------------------------------------
    File Name: custom.js
---------------------------------------------------------------------*/

// Safe fallbacks for optional / legacy jQuery plugins to prevent console errors
(function ($) {
	if (!$) return;
	var optionalPlugins = [
		'meanmenu',
		'sticky',
		'niceScroll',
		'niceSelect',
		'owlCarousel',
		'countdown',
		'slick',
		'fancybox',
		'tooltip',
		'carousel'
	];
	optionalPlugins.forEach(function (name) {
		if (!$.fn[name]) {
			$.fn[name] = function () {
				return this;
			};
		}
	});
})(window.jQuery);

if (typeof window !== 'undefined' && typeof window.Swiper === 'undefined') {
	window.Swiper = function () {
		return {
			on: function () {},
			destroy: function () {}
		};
	};
}

$(function () {

	"use strict";

	/* Preloader
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	setTimeout(function () {
		$('.loader_bg').fadeToggle();
	}, 1500);

	/* JQuery Menu
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.meanmenu && $('header nav').length) {
			$('header nav').meanmenu();
		}
	});

	/* Tooltip
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.tooltip && $('[data-toggle="tooltip"]').length) {
			$('[data-toggle="tooltip"]').tooltip();
		}
	});

	/* sticky
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.sticky && $(".sticky-wrapper-header").length) {
			$(".sticky-wrapper-header").sticky({ topSpacing: 0 });
		}
	});

	/* Mouseover
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		$(".main-menu ul li.megamenu").mouseover(function () {
			if (!$(this).parent().hasClass("#wrapper")) {
				$("#wrapper").addClass('overlay');
			}
		});
		$(".main-menu ul li.megamenu").mouseleave(function () {
			$("#wrapper").removeClass('overlay');
		});
	});

	/* NiceScroll
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	if ($.fn.niceScroll && $(".brand-box").length) {
		$(".brand-box").niceScroll({
			cursorcolor: "#9b9b9c",
		});
	}

	/* NiceSelect
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.niceSelect && $('select').length) {
			$('select').niceSelect();
		}
	});

	
	/* OwlCarousel - Blog Post slider
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.owlCarousel && $('.carousel-slider-post').length) {
			var owl = $('.carousel-slider-post');
			owl.owlCarousel({
				items: 1,
				loop: true,
				margin: 10,
				autoplay: true,
				autoplayTimeout: 3000,
				autoplayHoverPause: true
			});
		}
	});

	/* OwlCarousel - Banner Rotator Slider
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.owlCarousel && $('.banner-rotator-slider').length) {
			var owl = $('.banner-rotator-slider');
			owl.owlCarousel({
				items: 1,
				loop: true,
				margin: 10,
				nav: true,
				dots: false,
				navText: ["<i class='fa fa-angle-left'></i>", "<i class='fa fa-angle-right'></i>"],
				autoplay: true,
				autoplayTimeout: 3000,
				autoplayHoverPause: true
			});
		}
	});

	/* OwlCarousel - Product Slider
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(document).ready(function () {
		if ($.fn.owlCarousel && $('#product-in-slider').length) {
			var owl = $('#product-in-slider');
			owl.owlCarousel({
				loop: true,
				nav: true,
				margin: 10,
				navText: ["<i class='fa fa-angle-left'></i>", "<i class='fa fa-angle-right'></i>"],
				responsive: {
					0: {
						items: 1
					},
					600: {
						items: 2
					},
					960: {
						items: 3
					},
					1200: {
						items: 4
					}
				}
			});
			owl.on('mousewheel', '.owl-stage', function (e) {
				if (e.deltaY > 0) {
					owl.trigger('next.owl');
				} else {
					owl.trigger('prev.owl');
				}
				e.preventDefault();
			});
		}
	});

	/* Scroll to Top
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */

	$(window).on('scroll', function () {
		scroll = $(window).scrollTop();
		if (scroll >= 100) {
			$("#back-to-top").addClass('b-show_scrollBut')
		} else {
			$("#back-to-top").removeClass('b-show_scrollBut')
		}
	});
	$("#back-to-top").on("click", function () {
		$('body,html').animate({
			scrollTop: 0
		}, 1000);
	});

	/* Contact-form
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if ($.validator) {
		$.validator.setDefaults({
			submitHandler: function () {
				alert("submitted!");
			}
		});

		$(document).ready(function () {
			if ($("#contact-form").length) {
				$("#contact-form").validate({
					rules: {
						firstname: "required",
						email: {
							required: true,
							email: true
						},
						lastname: "required",
						message: "required",
						agree: "required"
					},
					messages: {
						firstname: "Please enter your firstname",
						email: "Please enter a valid email address",
						lastname: "Please enter your lastname",
						username: {
							required: "Please enter a username",
							minlength: "Your username must consist of at least 2 characters"
						},
						message: "Please enter your Message",
						agree: "Please accept our policy"
					},
					errorElement: "div",
					errorPlacement: function (error, element) {
						error.addClass("help-block");
						if (element.prop("type") === "checkbox") {
							error.insertAfter(element.parent("input"));
						} else {
							error.insertAfter(element);
						}
					},
					highlight: function (element, errorClass, validClass) {
						$(element).parents(".col-md-4, .col-md-12").addClass("has-error").removeClass("has-success");
					},
					unhighlight: function (element, errorClass, validClass) {
						$(element).parents(".col-md-4, .col-md-12").addClass("has-success").removeClass("has-error");
					}
				});
			}
		});
	}

	/* heroslider
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if (typeof Swiper !== 'undefined' && $('.heroslider').length) {
		new Swiper('.heroslider', {
			spaceBetween: 30,
			centeredSlides: true,
			slidesPerView: 'auto',
			paginationClickable: true,
			loop: true,
			autoplay: {
				delay: 2500,
				disableOnInteraction: false,
			},
			pagination: {
				el: '.swiper-pagination',
				clickable: true,
				dynamicBullets: true
			},
		});
	}

	/* Product Filters
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if (typeof Swiper !== 'undefined' && $('.swiper-product-filters').length) {
		new Swiper('.swiper-product-filters', {
			slidesPerView: 3,
			slidesPerColumn: 2,
			spaceBetween: 30,
			breakpoints: {
				1024: {
					slidesPerView: 3,
					spaceBetween: 30,
				},
				768: {
					slidesPerView: 2,
					spaceBetween: 30,
					slidesPerColumn: 1,
				},
				640: {
					slidesPerView: 2,
					spaceBetween: 20,
					slidesPerColumn: 1,
				},
				480: {
					slidesPerView: 1,
					spaceBetween: 10,
					slidesPerColumn: 1,
				}
			},
			pagination: {
				el: '.swiper-pagination',
				clickable: true,
				dynamicBullets: true
			}
		});
	}

	/* Countdown
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if ($.fn.countdown && $('[data-countdown]').length) {
		$('[data-countdown]').each(function () {
			var $this = $(this),
				finalDate = $(this).data('countdown');
			$this.countdown(finalDate, function (event) {
				var $this = $(this).html(event.strftime(''
					+ '<div class="time-bar"><span class="time-box">%w</span> <span class="line-b">weeks</span></div> '
					+ '<div class="time-bar"><span class="time-box">%d</span> <span class="line-b">days</span></div> '
					+ '<div class="time-bar"><span class="time-box">%H</span> <span class="line-b">hr</span></div> '
					+ '<div class="time-bar"><span class="time-box">%M</span> <span class="line-b">min</span></div> '
					+ '<div class="time-bar"><span class="time-box">%S</span> <span class="line-b">sec</span></div>'));
			});
		});
	}

	/* Deal Slider
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if ($.fn.slick && $('.deal-slider').length) {
		$('.deal-slider').slick({
			dots: false,
			infinite: false,
			prevArrow: '.previous-deal',
			nextArrow: '.next-deal',
			speed: 500,
			slidesToShow: 3,
			slidesToScroll: 3,
			responsive: [{
				breakpoint: 1024,
				settings: {
					slidesToShow: 3,
					slidesToScroll: 2,
					infinite: true,
					dots: false
				}
			}, {
				breakpoint: 768,
				settings: {
					slidesToShow: 2,
					slidesToScroll: 2
				}
			}, {
				breakpoint: 480,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}]
		});
	}

	/* News Slider
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if ($.fn.slick && $('#news-slider').length) {
		$('#news-slider').slick({
			dots: false,
			infinite: false,
			prevArrow: '.previous',
			nextArrow: '.next',
			speed: 500,
			slidesToShow: 1,
			slidesToScroll: 1,
			responsive: [{
				breakpoint: 1024,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1,
					infinite: true,
					dots: false
				}
			}, {
				breakpoint: 600,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}, {
				breakpoint: 480,
				settings: {
					slidesToShow: 1,
					slidesToScroll: 1
				}
			}]
		});
	}

	/* Fancybox
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if ($.fn.fancybox && $('.fancybox').length) {
		$(".fancybox").fancybox({
			maxWidth: 1200,
			maxHeight: 600,
			width: '70%',
			height: '70%',
		});
	}

	/* Toggle sidebar
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	$(document).ready(function () {
		$('#sidebarCollapse').on('click', function () {
			$('#sidebar').toggleClass('active');
			$(this).toggleClass('active');
		});
	});

	/* Product slider 
	-- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- */
	if ($.fn.carousel && $('#blogCarousel').length) {
		$('#blogCarousel').carousel({
			interval: 5000
		});
	}


});