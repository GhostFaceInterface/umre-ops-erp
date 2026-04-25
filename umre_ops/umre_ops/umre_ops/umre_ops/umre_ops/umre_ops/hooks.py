app_name = "umre_ops"
app_title = "Umre Ops"
app_publisher = "Sermed Turizm"
app_description = "Umre operasyon sistemi"
app_email = "sermedturizm1453@gmail.com"
app_license = "mit"

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "umre_ops",
# 		"logo": "/assets/umre_ops/logo.png",
# 		"title": "Umre Ops",
# 		"route": "/umre_ops",
# 		"has_permission": "umre_ops.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/umre_ops/css/umre_ops.css"
# app_include_js = "/assets/umre_ops/js/umre_ops.js"

# include js, css files in header of web template
# web_include_css = "/assets/umre_ops/css/umre_ops.css"
# web_include_js = "/assets/umre_ops/js/umre_ops.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "umre_ops/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "umre_ops/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "umre_ops.utils.jinja_methods",
# 	"filters": "umre_ops.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "umre_ops.install.before_install"
# after_install = "umre_ops.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "umre_ops.uninstall.before_uninstall"
# after_uninstall = "umre_ops.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "umre_ops.utils.before_app_install"
# after_app_install = "umre_ops.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "umre_ops.utils.before_app_uninstall"
# after_app_uninstall = "umre_ops.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "umre_ops.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "umre_ops.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"umre_ops.tasks.all"
# 	],
# 	"daily": [
# 		"umre_ops.tasks.daily"
# 	],
# 	"hourly": [
# 		"umre_ops.tasks.hourly"
# 	],
# 	"weekly": [
# 		"umre_ops.tasks.weekly"
# 	],
# 	"monthly": [
# 		"umre_ops.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "umre_ops.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "umre_ops.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "umre_ops.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "umre_ops.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["umre_ops.utils.before_request"]
# after_request = ["umre_ops.utils.after_request"]

# Job Events
# ----------
# before_job = ["umre_ops.utils.before_job"]
# after_job = ["umre_ops.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"umre_ops.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

