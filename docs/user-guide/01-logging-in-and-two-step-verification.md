# 1. Logging in and two-step verification

*User guide, chapter 1 · Last updated 21 October 2026*

**Who this is for:** everyone. Admins and staff must use two-step verification.

## 1.1 Log in

1. Open your business's address, for example `https://gorkhabutchery.<platform-domain>/admin/`.
2. Enter your **email** and **password**, then click **Log in**.

Each business has its own logins. An account for one business does not work on another business's site.

> **Too many wrong passwords?** After 5 wrong tries, the account is locked for 15 minutes, even with the right password. Wait, then try again, or use **Forgotten your password?**

*Screenshot: login page (added automatically when the user-guide screenshots are built, task 1.17)*

## 1.2 Set up two-step verification (first login)

The first time an admin logs in, the **Set up two-step verification** page opens.

1. Install an authenticator app on your phone: **Microsoft Authenticator** or **Google Authenticator**.
2. In the app, tap **Add account** and scan the QR code on the screen.
   - Can't scan? Type the key shown under the QR code into the app instead.
3. Type the **6-digit code** from the app and click **Turn on**.
4. **Save your 10 backup codes.** They are shown only once. Each code works once, if you lose your phone.
5. Click **I have saved my codes – continue**.

*Screenshot: set up two-step verification*

## 1.3 Log in with two-step verification (every time after)

1. Log in with your email and password.
2. Open your authenticator app and type the current 6-digit code.
3. Click **Verify**.

If a code does not work, wait a few seconds and type the **newest** code. Check that the time on your phone is set automatically.

## 1.4 Lost your phone?

- Log in and enter one of your **backup codes** instead of the 6-digit code.
- Or ask another admin of your business to open **Users**, tick your name, choose **Reset two-step verification**, and click **Go**. You will set it up again at your next login.

Admins cannot reset their own two-step verification. Ask another admin, or platform support.

## 1.5 Forgot your password?

1. On the login page, click **Forgotten your password?**
2. Enter your email. If an account exists, you get an email with a reset link.
3. The link works for **1 hour**. Choose a new password (at least 12 characters).

## 1.6 Login history

Admins can see every login, failed attempt, lockout and two-step verification event under **Accounts → Login events**. The history cannot be edited or deleted.
