"""
Django management command to monitor and refresh OAuth tokens
Run this every hour via cron or scheduled task

Usage: python manage.py monitor_tokens
"""

from django.core.management.base import BaseCommand
from platforms.token_manager import TokenManager


class Command(BaseCommand):
    help = 'Monitor OAuth tokens for expiry and refresh if needed. Also check API quotas.'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--reset-quota',
            action='store_true',
            help='Reset monthly API quotas for all accounts'
        )
    
    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))
        self.stdout.write(self.style.SUCCESS('🚀 Starting Token & Quota Monitoring...'))
        self.stdout.write(self.style.SUCCESS('='*80))
        
        # Check token expiry and auto-refresh
        token_summary = TokenManager.check_token_expiry()
        
        # Check API quota usage
        quota_summary = TokenManager.check_api_quota()
        
        # Print detailed summary
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))
        self.stdout.write(self.style.SUCCESS('📋 MONITORING SUMMARY'))
        self.stdout.write(self.style.SUCCESS('='*80))
        
        self.stdout.write(f"\n🔐 TOKEN STATUS:")
        self.stdout.write(f"  ✅ Total Active Tokens: {token_summary['total_tokens']}")
        self.stdout.write(f"  ❌ Expired: {len(token_summary['expired'])}")
        self.stdout.write(f"  ⚠️  Expiring Soon (7 days): {len(token_summary['expiring_soon'])}")
        self.stdout.write(f"  🔄 Auto-Refreshed: {len(token_summary['refreshed'])}")
        self.stdout.write(f"  ❌ Invalid: {len(token_summary['invalid'])}")
        
        self.stdout.write(f"\n📦 API QUOTA STATUS:")
        self.stdout.write(f"  ✅ Total Accounts: {quota_summary['total_accounts']}")
        self.stdout.write(f"  ❌ Quota Exceeded: {len(quota_summary['quota_exceeded'])}")
        self.stdout.write(f"  ⚠️  High Usage (80%+): {len(quota_summary['high_usage'])}")
        self.stdout.write(f"  ✅ Normal Usage: {len(quota_summary['normal_usage'])}")
        self.stdout.write(f"  ⭕ Unused: {len(quota_summary['unused'])}")
        
        # Print details if there are issues
        if token_summary['expired']:
            self.stdout.write(self.style.ERROR(f"\n❌ EXPIRED TOKENS:"))
            for item in token_summary['expired']:
                self.stdout.write(f"   - {item['user']} ({item['platform']} - {item['account']})")
                self.stdout.write(f"     Expired at: {item['expired_at']}")
        
        if token_summary['expiring_soon']:
            self.stdout.write(self.style.WARNING(f"\n⚠️  EXPIRING SOON (7 days):"))
            for item in token_summary['expiring_soon']:
                self.stdout.write(f"   - {item['user']} ({item['platform']} - {item['account']})")
                self.stdout.write(f"     Expires in: {item['expires_in_days']} days ({item['expiry_date']})")
        
        if quota_summary['quota_exceeded']:
            self.stdout.write(self.style.ERROR(f"\n❌ QUOTA EXCEEDED:"))
            for item in quota_summary['quota_exceeded']:
                self.stdout.write(f"   - {item['user']} ({item['platform']} - {item['account']})")
                self.stdout.write(f"     Usage: {item['usage']} ({item['percentage']})")
        
        if quota_summary['high_usage']:
            self.stdout.write(self.style.WARNING(f"\n⚠️  HIGH USAGE (80%+):"))
            for item in quota_summary['high_usage']:
                self.stdout.write(f"   - {item['user']} ({item['platform']} - {item['account']})")
                self.stdout.write(f"     Usage: {item['usage']} ({item['percentage']})")
        
        # Reset monthly quota if requested
        if options['reset_quota']:
            self.stdout.write(self.style.SUCCESS(f"\n🔄 RESETTING MONTHLY QUOTAS..."))
            reset_count = TokenManager.reset_monthly_quota()
            self.stdout.write(self.style.SUCCESS(f"✅ Reset {reset_count} accounts"))
        
        self.stdout.write(self.style.SUCCESS('\n' + '='*80))
        self.stdout.write(self.style.SUCCESS('✅ Monitoring Complete!'))
        self.stdout.write(self.style.SUCCESS('='*80 + '\n'))
