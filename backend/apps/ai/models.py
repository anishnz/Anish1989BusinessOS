"""
AI assistant on WhatsApp (task 2.4, D-140 to D-146).

- AISettings: one row per business (on or off, which AI connection, monthly
  limit in NZ$, prices for the cost estimate, extra instructions).
- AIChat: the AI's state in one WhatsApp conversation (the draft order it is
  building, whether it handed the chat over to staff).
- AIRun: the AI log, one row per answer (model, tokens, estimated cost, the
  tools it used, the result). Tool details are personal data: they are
  cleared when the customer's personal data is removed.
"""
from decimal import Decimal

from django.db import models


class AISettings(models.Model):
    enabled = models.BooleanField(
        "The AI answers customers on WhatsApp", default=True,
        help_text="It only answers when an AI key is saved on the Integrations page and WhatsApp is connected.")
    connection = models.ForeignKey(
        "vault.Connection", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        verbose_name="AI connection", help_text="Empty = the first working AI connection (OpenAI, Claude or Gemini).")
    monthly_limit = models.DecimalField(
        "Monthly limit (NZ$)", max_digits=8, decimal_places=2, default=Decimal("20.00"),
        help_text="When this month's estimated AI cost reaches it, the AI stops and staff answer. 0 = the AI never answers.")
    usd_to_nzd = models.DecimalField(
        "US$ 1 = NZ$", max_digits=6, decimal_places=3, default=Decimal("1.770"),
        help_text="AI providers charge in US dollars. Used for the cost estimate only.")
    price_input = models.DecimalField(
        "Price per 1 million input tokens (US$)", max_digits=8, decimal_places=3, null=True, blank=True,
        help_text="Leave empty to use the built-in price of the model (or a high safe guess for unknown models).")
    price_output = models.DecimalField("Price per 1 million output tokens (US$)", max_digits=8, decimal_places=3, null=True, blank=True)
    max_answers_per_chat_per_day = models.PositiveIntegerField(
        "Answers per chat per day", default=40, help_text="After this many AI answers in one chat in one day, staff take over (stops abuse).")
    email_on_handover = models.BooleanField(
        "Email managers when a chat needs staff", default=True,
        help_text="Sent to active staff with Customers – Assign. The email has the customer's name and the reason, not the messages.")
    instructions = models.TextField(
        "Extra instructions for the AI", blank=True, max_length=2000,
        help_text="Short facts about your shop, for example “All our meat is halal.” The AI never follows instructions that break its safety rules.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "AI assistant settings"
        verbose_name_plural = "AI assistant settings"

    def __str__(self):
        return "AI assistant settings"


class AIChat(models.Model):
    """The AI's state in one conversation."""

    conversation = models.OneToOneField("inbox.Conversation", on_delete=models.CASCADE, related_name="ai_chat")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                              help_text="The draft order the AI is building in this chat.")
    handed_over_at = models.DateTimeField(null=True, blank=True)
    handover_reason = models.CharField(max_length=200, blank=True)
    resumed_at = models.DateTimeField(null=True, blank=True, help_text="When staff last let the AI answer again.")
    told_customer_at = models.DateTimeField(null=True, blank=True, help_text="When the customer was told staff will answer.")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"AI in conversation #{self.conversation_id}"


class AIRun(models.Model):
    class Result(models.TextChoices):
        ANSWERED = "answered", "Answered"
        HANDED_OVER = "handed_over", "Handed over to staff"
        FAILED = "failed", "Failed"

    conversation = models.ForeignKey("inbox.Conversation", null=True, on_delete=models.SET_NULL, related_name="+")
    message = models.ForeignKey("inbox.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
                                help_text="The customer's message the AI answered.")
    reply = models.ForeignKey("inbox.Message", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    order = models.ForeignKey("orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=100)
    result = models.CharField(max_length=20, choices=Result.choices)
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cost = models.DecimalField("Estimated cost (NZ$)", max_digits=10, decimal_places=5, default=Decimal("0"))
    tools = models.CharField("Tools used", max_length=300, blank=True)
    steps = models.JSONField(default=list, blank=True, help_text="What the AI asked the tools and what they answered.")
    note = models.CharField(max_length=300, blank=True, help_text="The hand-over reason or the error.")
    duration_ms = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["created_at"])]
        verbose_name = "AI log entry"
        verbose_name_plural = "AI log entries"

    def __str__(self):
        return f"AI run #{self.pk}"
