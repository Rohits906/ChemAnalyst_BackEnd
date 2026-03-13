"""
Token management utilities for user social accounts
Handles token refresh, expiry monitoring, and API quota tracking
"""

import logging
import requests
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import UserSocialAccount

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages OAuth tokens for user social accounts"""
    
    @staticmethod
    def refresh_facebook_token(social_account: UserSocialAccount) -> bool:
        """
        Refresh Facebook long-lived token before expiry
        Returns True if successful, False otherwise
        """
        try:
            print(f"\n🔄 [TOKEN REFRESH] Refreshing token for {social_account.user.username} - {social_account.platform}")
            
            # Exchange long-lived token for another one
            url = f"https://graph.facebook.com/v{settings.FACEBOOK_API_VERSION}/oauth/access_token"
            params = {
                'grant_type': 'fb_exchange_token',
                'client_id': settings.FACEBOOK_APP_ID,
                'client_secret': settings.FACEBOOK_APP_SECRET,
                'fb_exchange_token': social_account.access_token,
            }
            
            response = requests.get(url, params=params)
            data = response.json()
            
            if 'error' in data:
                error_msg = data['error'].get('message', 'Unknown error')
                print(f"❌ [TOKEN REFRESH] Error refreshing token: {error_msg}")
                social_account.is_token_valid = False
                social_account.save()
                logger.error(f"Token refresh failed for {social_account}: {error_msg}")
                return False
            
            # Update token and expiry
            new_token = data.get('access_token')
            expires_in = data.get('expires_in', 5184000)  # Default 60 days
            
            social_account.access_token = new_token
            social_account.token_expiry = timezone.now() + timedelta(seconds=expires_in)
            social_account.last_token_refreshed = timezone.now()
            social_account.is_token_valid = True
            social_account.save()
            
            days_until_expiry = social_account.days_until_expiry()
            print(f"✅ [TOKEN REFRESH] TOKEN REFRESHED for {social_account.user.username} - Expires in {days_until_expiry} days")
            logger.info(f"Token refreshed for {social_account}: Expires in {days_until_expiry} days")
            
            return True
            
        except Exception as e:
            print(f"❌ [TOKEN REFRESH] Exception while refreshing: {str(e)}")
            logger.error(f"Exception during token refresh for {social_account}: {e}", exc_info=True)
            return False
    
    @staticmethod
    def check_token_expiry() -> dict:
        """
        Check all user tokens and alert on expiry
        Returns summary of token status
        """
        print("\n📊 [TOKEN MONITOR] Checking token expiry status...")
        
        summary = {
            'total_tokens': 0,
            'expired': [],
            'expiring_soon': [],  # Within 7 days
            'refreshed': [],
            'invalid': []
        }
        
        # Get all active social accounts
        accounts = UserSocialAccount.objects.filter(is_token_valid=True)
        summary['total_tokens'] = accounts.count()
        
        print(f"📊 [TOKEN MONITOR] Checking {summary['total_tokens']} active tokens...")
        
        for account in accounts:
            username = account.user.username
            platform = account.platform.upper()
            account_name = account.account_name
            days_left = account.days_until_expiry()
            
            if account.is_token_expired():
                print(f"⚠️  [TOKEN EXPIRED] {username} - {platform} ({account_name}) - EXPIRED!")
                summary['expired'].append({
                    'user': username,
                    'platform': platform,
                    'account': account_name,
                    'expired_at': account.token_expiry.isoformat()
                })
                account.is_token_valid = False
                account.save()
                
            elif days_left <= 7:
                print(f"⚠️  [TOKEN EXPIRING] {username} - {platform} ({account_name}) - Expires in {days_left} days!")
                summary['expiring_soon'].append({
                    'user': username,
                    'platform': platform,
                    'account': account_name,
                    'expires_in_days': days_left,
                    'expiry_date': account.token_expiry.isoformat()
                })
                
                # Auto-refresh tokens expiring within 7 days
                if TokenManager.refresh_facebook_token(account):
                    summary['refreshed'].append({
                        'user': username,
                        'platform': platform,
                        'account': account_name
                    })
            else:
                print(f"✅ [TOKEN HEALTHY] {username} - {platform} ({account_name}) - Expires in {days_left} days")
        
        # Check for invalid tokens
        invalid_accounts = UserSocialAccount.objects.filter(is_token_valid=False)
        for account in invalid_accounts:
            print(f"❌ [TOKEN INVALID] {account.user.username} - {account.platform.upper()} ({account.account_name}) - INVALID TOKEN!")
            summary['invalid'].append({
                'user': account.user.username,
                'platform': account.platform.upper(),
                'account': account.account_name,
                'marked_invalid_at': account.last_token_refreshed.isoformat() if account.last_token_refreshed else 'N/A'
            })
        
        print(f"\n📊 [TOKEN MONITOR] Summary:")
        print(f"   Total Tokens: {summary['total_tokens']}")
        print(f"   Expired: {len(summary['expired'])}")
        print(f"   Expiring Soon: {len(summary['expiring_soon'])}")
        print(f"   Auto-Refreshed: {len(summary['refreshed'])}")
        print(f"   Invalid: {len(summary['invalid'])}")
        
        return summary
    
    @staticmethod
    def check_api_quota() -> dict:
        """
        Check API quota usage for all users
        Returns summary of quota status
        """
        print("\n📦 [API QUOTA MONITOR] Checking API quota usage...")
        
        summary = {
            'total_accounts': 0,
            'quota_exceeded': [],
            'high_usage': [],  # 80% or more
            'normal_usage': [],
            'unused': []
        }
        
        accounts = UserSocialAccount.objects.all()
        summary['total_accounts'] = accounts.count()
        
        print(f"📦 [API QUOTA MONITOR] Checking {summary['total_accounts']} accounts...")
        
        for account in accounts:
            username = account.user.username
            platform = account.platform.upper()
            account_name = account.account_name
            usage_pct = account.get_usage_percentage()
            calls_made = account.api_calls_made
            limit = account.api_calls_limit
            
            if account.api_quota_exceeded():
                print(f"❌ [QUOTA EXCEEDED] {username} - {platform} ({account_name}) - {calls_made}/{limit} ({usage_pct:.1f}%)")
                summary['quota_exceeded'].append({
                    'user': username,
                    'platform': platform,
                    'account': account_name,
                    'usage': f"{calls_made}/{limit}",
                    'percentage': f"{usage_pct:.1f}%"
                })
                
            elif usage_pct >= 80:
                print(f"⚠️  [HIGH USAGE] {username} - {platform} ({account_name}) - {calls_made}/{limit} ({usage_pct:.1f}%)")
                summary['high_usage'].append({
                    'user': username,
                    'platform': platform,
                    'account': account_name,
                    'usage': f"{calls_made}/{limit}",
                    'percentage': f"{usage_pct:.1f}%"
                })
                
            else:
                usage_status = f"{calls_made}/{limit}" if calls_made > 0 else "Unused"
                status_emoji = "✅" if calls_made > 0 else "⭕"
                print(f"{status_emoji} [NORMAL USAGE] {username} - {platform} ({account_name}) - {usage_status} ({usage_pct:.1f}%)")
                
                if calls_made == 0:
                    summary['unused'].append({
                        'user': username,
                        'platform': platform,
                        'account': account_name
                    })
                else:
                    summary['normal_usage'].append({
                        'user': username,
                        'platform': platform,
                        'account': account_name,
                        'usage': f"{calls_made}/{limit}",
                        'percentage': f"{usage_pct:.1f}%"
                    })
        
        print(f"\n📦 [API QUOTA MONITOR] Summary:")
        print(f"   Total Accounts: {summary['total_accounts']}")
        print(f"   Quota Exceeded: {len(summary['quota_exceeded'])}")
        print(f"   High Usage (80%+): {len(summary['high_usage'])}")
        print(f"   Normal Usage: {len(summary['normal_usage'])}")
        print(f"   Unused: {len(summary['unused'])}")
        
        return summary
    
    @staticmethod
    def record_api_call(social_account: UserSocialAccount, calls: int = 1) -> bool:
        """
        Record API call usage for a social account
        Returns True if within quota, False if exceeded
        """
        social_account.api_calls_made += calls
        
        if social_account.api_quota_exceeded():
            usage_pct = social_account.get_usage_percentage()
            print(f"❌ [QUOTA LIMIT] {social_account.user.username} - {social_account.platform.upper()} - QUOTA EXCEEDED! ({social_account.api_calls_made}/{social_account.api_calls_limit}, {usage_pct:.1f}%)")
            logger.error(f"API quota exceeded for {social_account}: {social_account.api_calls_made}/{social_account.api_calls_limit}")
            social_account.save()
            return False
        
        # Warn at high usage
        usage_pct = social_account.get_usage_percentage()
        if usage_pct >= 90:
            print(f"⚠️  [QUOTA WARNING] {social_account.user.username} - {social_account.platform.upper()} - HIGH USAGE! ({social_account.api_calls_made}/{social_account.api_calls_limit}, {usage_pct:.1f}%)")
        
        social_account.save()
        return True
    
    @staticmethod
    def reset_monthly_quota():
        """Reset API quota for all accounts (run once per month)"""
        print("\n🔄 [QUOTA RESET] Resetting monthly API quotas...")
        
        accounts = UserSocialAccount.objects.all()
        reset_count = 0
        
        for account in accounts:
            account.api_calls_made = 0
            account.last_reset_date = timezone.now()
            account.save()
            reset_count += 1
            print(f"✅ [QUOTA RESET] Reset quota for {account.user.username} - {account.platform.upper()} ({account.account_name})")
        
        print(f"\n✅ [QUOTA RESET] Reset complete! Total accounts: {reset_count}")
        return reset_count
