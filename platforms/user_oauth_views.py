"""
User-specific OAuth flow for Facebook
This handles multi-tenant OAuth where each user connects their own accounts
"""

import requests
import logging
import json
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.contrib.auth.models import User

from .models import UserSocialAccount, Platform, ChannelStats, ChannelPost
from .token_manager import TokenManager

logger = logging.getLogger(__name__)


class FacebookUserOAuthInitiateView(APIView):
    """
    Initiate OAuth flow for a user to connect their Facebook account
    User-specific endpoint that stores token in UserSocialAccount model
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get Facebook OAuth authorization URL
        Frontend redirects user to this URL
        """
        try:
            print(f"\n🔐 [FACEBOOK OAUTH] Initiating OAuth for user: {request.user.username}")
            
            # Build callback URI
            redirect_uri = request.build_absolute_uri(
                reverse('facebook-user-oauth-callback')
            )
            
            # Meta prefers localhost over 127.0.0.1
            if "127.0.0.1" in redirect_uri:
                redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
            
            # OAuth scopes for user
            # These scopes are valid. If you get "Invalid Scopes" error, your app isn't properly
            # configured in Facebook Developer Console. See FACEBOOK_APP_REVIEW_GUIDE.md
            scopes = [
                'pages_read_engagement',  # Read page insights
                'pages_read_user_content',  # Read page posts  
                'pages_show_list',  # See list of pages user manages
            ]
            
            # Build auth URL
            auth_url = (
                f"https://www.facebook.com/{settings.FACEBOOK_API_VERSION}/dialog/oauth"
                f"?client_id={settings.FACEBOOK_APP_ID}"
                f"&redirect_uri={redirect_uri}"
                f"&scope={','.join(scopes)}"
                f"&response_type=code"
                f"&state={request.user.id}"  # Pass user ID in state
            )
            
            print(f"✅ [FACEBOOK OAUTH] Generated auth URL for {request.user.username}")
            
            return Response({
                "auth_url": auth_url,
                "redirect_uri": redirect_uri,
                "platform": "facebook",
                "user": request.user.username
            })
            
        except Exception as e:
            print(f"❌ [FACEBOOK OAUTH] Error generating auth URL: {str(e)}")
            logger.error(f"Error generating Facebook OAuth URL: {e}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class FacebookUserOAuthCallbackView(APIView):
    """
    Handle Facebook OAuth callback
    Exchange code for tokens and store in UserSocialAccount
    """
    permission_classes = []  # No auth required for callback
    
    def get(self, request):
        """
        Handle OAuth callback from Facebook
        """
        try:
            frontend_url = settings.FRONTEND_URL.rstrip('/')
            
            # Get parameters from Facebook
            code = request.GET.get('code')
            state = request.GET.get('state')  # User ID
            error = request.GET.get('error')
            error_description = request.GET.get('error_description')
            
            print(f"\n🔐 [FACEBOOK OAUTH CALLBACK] Received callback")
            print(f"   State (User ID): {state}")
            print(f"   Code: {code[:20]}..." if code else "   Code: None")
            print(f"   Error: {error}" if error else "   Error: None")
            
            # Handle OAuth error
            if error or not code or not state:
                print(f"❌ [FACEBOOK OAUTH CALLBACK] OAuth error: {error or 'No code/state'}")
                error_msg = error or (error_description if error_description else 'access_denied')
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=facebook&reason={error_msg}"
                )
            
            # Get user from state
            try:
                user = User.objects.get(id=state)
                print(f"✅ [FACEBOOK OAUTH CALLBACK] User identified: {user.username}")
            except User.DoesNotExist:
                print(f"❌ [FACEBOOK OAUTH CALLBACK] User not found for ID: {state}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=facebook&reason=user_not_found"
                )
            
            # Exchange code for tokens
            print(f"🔄 [FACEBOOK OAUTH CALLBACK] Exchanging code for tokens...")
            token_response = requests.post(
                f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/oauth/access_token",
                data={
                    'client_id': settings.FACEBOOK_APP_ID,
                    'client_secret': settings.FACEBOOK_APP_SECRET,
                    'redirect_uri': request.build_absolute_uri(reverse('facebook-user-oauth-callback')),
                    'code': code,
                }
            )
            
            token_data = token_response.json()
            
            if 'error' in token_data:
                error_msg = token_data['error'].get('message', 'Token exchange failed')
                print(f"❌ [FACEBOOK OAUTH CALLBACK] Token exchange error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=facebook&reason={error_msg}"
                )
            
            short_lived_token = token_data.get('access_token')
            print(f"✅ [FACEBOOK OAUTH CALLBACK] Got short-lived token")
            
            # Exchange for long-lived token
            print(f"🔄 [FACEBOOK OAUTH CALLBACK] Exchanging for long-lived token...")
            long_lived_response = requests.get(
                f"https://graph.facebook.com/{settings.FACEBOOK_API_VERSION}/oauth/access_token",
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': settings.FACEBOOK_APP_ID,
                    'client_secret': settings.FACEBOOK_APP_SECRET,
                    'fb_exchange_token': short_lived_token,
                }
            )
            
            long_lived_data = long_lived_response.json()
            
            if 'error' in long_lived_data:
                error_msg = long_lived_data['error'].get('message', 'Failed to get long-lived token')
                print(f"❌ [FACEBOOK OAUTH CALLBACK] Long-lived token error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=facebook&reason={error_msg}"
                )
            
            long_lived_token = long_lived_data.get('access_token')
            expires_in = long_lived_data.get('expires_in', 5184000)  # Default 60 days
            token_expiry = timezone.now() + timedelta(seconds=expires_in)
            
            print(f"✅ [FACEBOOK OAUTH CALLBACK] Got long-lived token (expires in {expires_in}s = ~{expires_in//86400} days)")
            
            # Get user's pages
            print(f"🔄 [FACEBOOK OAUTH CALLBACK] Fetching user's pages...")
            pages_response = requests.get(
                f"https://graph.facebook.com/me/accounts",
                params={
                    'fields': 'id,name,access_token',
                    'access_token': long_lived_token,
                }
            )
            
            pages_data = pages_response.json()
            
            if 'error' in pages_data:
                error_msg = pages_data['error'].get('message', 'Failed to get pages')
                print(f"❌ [FACEBOOK OAUTH CALLBACK] Pages fetch error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=facebook&reason={error_msg}"
                )
            
            pages = pages_data.get('data', [])
            print(f"✅ [FACEBOOK OAUTH CALLBACK] Retrieved {len(pages)} page(s)")
            
            if not pages:
                print(f"⚠️  [FACEBOOK OAUTH CALLBACK] User has no pages")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=facebook&reason=no_pages"
                )
            
            # Store each page as a UserSocialAccount
            stored_accounts = []
            for page in pages:
                print(f"\n📝 [FACEBOOK OAUTH CALLBACK] Processing page: {page['name']}")
                
                account, created = UserSocialAccount.objects.update_or_create(
                    user=user,
                    platform='facebook',
                    account_id=page['id'],
                    defaults={
                        'access_token': page['access_token'],
                        'account_name': page['name'],
                        'account_email': '',
                        'profile_picture_url': '',
                        'token_expiry': token_expiry,
                        'is_token_valid': True,
                        'scopes': ['pages_read_engagement', 'pages_read_user_content'],
                        'api_calls_made': 0,
                        'api_calls_limit': 1000,  # Free tier
                    }
                )
                
                status_text = "Created" if created else "Updated"
                print(f"✅ [FACEBOOK OAUTH CALLBACK] {status_text} UserSocialAccount for {page['name']}")
                stored_accounts.append(account)
                
                # Also create/update Platform record for backwards compatibility
                platform, _ = Platform.objects.update_or_create(
                    user=user,
                    name='facebook',
                    channel_id=page['id'],
                    defaults={
                        'channel_name': page['name'],
                        'channel_url': f"https://facebook.com/{page['id']}",
                        'is_active': True,
                        'metadata': {
                            'account_id': page['id'],
                            'page_name': page['name'],
                            'page_access_token': page['access_token'],
                            'oauth_version': 'user-specific',
                            'account_type': 'facebook_page',
                        }
                    }
                )
            
            print(f"\n✅ [FACEBOOK OAUTH CALLBACK] OAuth callback completed!")
            print(f"   User: {user.username}")
            print(f"   Accounts stored: {len(stored_accounts)}")
            print(f"   Token expiry: {token_expiry.isoformat()}")
            print(f"   Days until expiry: {(token_expiry - timezone.now()).days}")
            
            # Redirect to platforms page with success indicator
            return HttpResponseRedirect(
                f"{frontend_url}/platforms"
                f"?oauth_success=true&platform=facebook&count={len(stored_accounts)}"
            )
            
        except Exception as e:
            print(f"❌ [FACEBOOK OAUTH CALLBACK] Exception: {str(e)}")
            import traceback
            traceback.print_exc()
            logger.error(f"Facebook OAuth callback error: {e}", exc_info=True)
            
            return HttpResponseRedirect(
                f"{frontend_url}/platforms"
                f"?oauth_error=true&platform=facebook&reason=internal_error"
            )


class UserSocialAccountsView(APIView):
    """
    List all connected social accounts for a user
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """Get all social accounts for the user"""
        accounts = UserSocialAccount.objects.filter(user=request.user)
        
        account_list = []
        for account in accounts:
            days_left = account.days_until_expiry()
            usage_pct = account.get_usage_percentage()
            
            account_list.append({
                'id': str(account.id),
                'platform': account.platform,
                'account_name': account.account_name,
                'account_email': account.account_email,
                'connected_at': account.connected_at.isoformat(),
                'token_valid': account.is_token_valid,
                'token_expiry': account.token_expiry.isoformat(),
                'days_until_expiry': days_left,
                'api_calls_made': account.api_calls_made,
                'api_calls_limit': account.api_calls_limit,
                'usage_percentage': round(usage_pct, 2),
                'quota_exceeded': account.api_quota_exceeded(),
            })
        
        return Response({
            'success': True,
            'total_accounts': len(account_list),
            'accounts': account_list
        })
    
    def delete(self, request):
        """Disconnect a social account"""
        account_id = request.query_params.get('id')
        
        try:
            account = UserSocialAccount.objects.get(id=account_id, user=request.user)
            account_name = f"{account.platform} - {account.account_name}"
            account.delete()
            
            # Also delete associated Platform records
            Platform.objects.filter(
                user=request.user,
                name=account.platform,
                channel_id=account.account_id
            ).delete()
            
            print(f"✅ [DISCONNECT] {request.user.username} disconnected {account_name}")
            
            return Response({
                'success': True,
                'message': f'Disconnected {account_name}'
            })
        except UserSocialAccount.DoesNotExist:
            return Response(
                {'error': 'Account not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Error disconnecting account: {e}")
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class InstagramUserOAuthInitiateView(APIView):
    """
    Initiate OAuth flow for a user to connect their Instagram account
    Supports both personal and business Instagram accounts
    """
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        """
        Get Instagram OAuth authorization URL
        Frontend redirects user to this URL
        """
        try:
            print(f"\n🔐 [INSTAGRAM OAUTH] Initiating OAuth for user: {request.user.username}")
            
            # Build callback URI
            redirect_uri = request.build_absolute_uri(
                reverse('instagram-user-oauth-callback')
            )
            
            # Meta prefers localhost over 127.0.0.1
            if "127.0.0.1" in redirect_uri:
                redirect_uri = redirect_uri.replace("127.0.0.1", "localhost")
            
            # OAuth scopes for Instagram
            # Strictly for Business accounts which require a linked Facebook Page
            scopes = [
                'instagram_basic',
                'instagram_manage_insights',
                'pages_read_engagement',
                'pages_show_list',
            ]
            
            # Build auth URL (Instagram uses Facebook's OAuth endpoint)
            auth_url = (
                f"https://www.facebook.com/{settings.FACEBOOK_API_VERSION}/dialog/oauth"
                f"?client_id={settings.FACEBOOK_APP_ID}"
                f"&redirect_uri={redirect_uri}"
                f"&scope={','.join(scopes)}"
                f"&response_type=code"
                f"&state={request.user.id}"  # Pass user ID in state
            )
            
            print(f"✅ [INSTAGRAM OAUTH] Generated auth URL for {request.user.username}")
            
            return Response({
                "auth_url": auth_url,
                "redirect_uri": redirect_uri,
                "platform": "instagram",
                "user": request.user.username
            })
            
        except Exception as e:
            print(f"❌ [INSTAGRAM OAUTH] Error generating auth URL: {str(e)}")
            logger.error(f"Error generating Instagram OAuth URL: {e}", exc_info=True)
            return Response(
                {"error": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class InstagramUserOAuthCallbackView(APIView):
    """
    Handle Instagram OAuth callback
    Exchange code for tokens and store in UserSocialAccount
    Supports personal and business accounts
    """
    permission_classes = []  # No auth required for callback
    
    def get(self, request):
        """
        Handle OAuth callback from Instagram
        """
        try:
            frontend_url = settings.FRONTEND_URL.rstrip('/')
            code = request.query_params.get('code')
            error = request.query_params.get('error')
            state = request.query_params.get('state')  # User ID
            
            print(f"\n🔐 [INSTAGRAM OAUTH CALLBACK] Received callback")
            print(f"   State (User ID): {state}")
            print(f"   Code: {code[:20]}..." if code else "   Code: None")
            print(f"   Error: {error}")
            
            # Handle OAuth errors
            if error or not code:
                error_msg = error or 'Unknown error'
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] OAuth error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason=access_denied"
                )
            
            # Get user from state
            try:
                user = User.objects.get(id=state)
            except User.DoesNotExist:
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] User not found with ID: {state}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason=user_not_found"
                )
            
            print(f"✅ [INSTAGRAM OAUTH CALLBACK] User identified: {user.username}")
            
            # Exchange code for short-lived token (Instagram uses Facebook's token endpoint)
            print(f"🔄 [INSTAGRAM OAUTH CALLBACK] Exchanging code for tokens...")
            token_response = requests.post(
                "https://graph.facebook.com/v19.0/oauth/access_token",
                data={
                    'client_id': settings.FACEBOOK_APP_ID,
                    'client_secret': settings.FACEBOOK_APP_SECRET,
                    'grant_type': 'authorization_code',
                    'redirect_uri': request.build_absolute_uri(
                        reverse('instagram-user-oauth-callback')
                    ).replace('127.0.0.1', 'localhost'),
                    'code': code,
                }
            )
            
            token_data = token_response.json()
            
            if 'error' in token_data:
                error_msg = token_data['error'].get('message', 'Token exchange failed')
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] Token exchange error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason={error_msg}"
                )
            
            short_lived_token = token_data.get('access_token')
            print(f"✅ [INSTAGRAM OAUTH CALLBACK] Got short-lived token")
            
            # For Instagram, we use the Facebook token to get Instagram Business Account info
            # First, get the Instagram Business Account ID associated with this Facebook user
            print(f"🔄 [INSTAGRAM OAUTH CALLBACK] Fetching Instagram Business Account ID...")
            ig_accounts_response = requests.get(
                f"https://graph.facebook.com/v19.0/me/instagram_accounts",
                params={
                    'fields': 'id,username,name,profile_picture_url,biography',
                    'access_token': short_lived_token,
                }
            )
            
            ig_accounts_data = ig_accounts_response.json()
            print(f"🔍 [INSTAGRAM OAUTH CALLBACK] Instagram accounts response: {ig_accounts_data}")  # Debug
            
            if 'error' in ig_accounts_data:
                error_msg = ig_accounts_data['error'].get('message', 'Failed to get Instagram accounts')
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] Instagram accounts error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason={error_msg}"
                )
            
            ig_accounts = ig_accounts_data.get('data', [])
            if not ig_accounts:
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] No Instagram Business Accounts found")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason=no_instagram_accounts"
                )
            
            instagram_account = ig_accounts[0]  # Get first account
            instagram_user_id = instagram_account.get('id')
            print(f"✅ [INSTAGRAM OAUTH CALLBACK] Got Instagram user ID: {instagram_user_id}")
            
            # For long-lived token, we exchange it using the graph.facebook.com endpoint
            print(f"🔄 [INSTAGRAM OAUTH CALLBACK] Exchanging for long-lived token...")
            long_lived_response = requests.get(
                f"https://graph.facebook.com/v19.0/oauth/access_token",
                params={
                    'grant_type': 'fb_exchange_token',
                    'client_id': settings.FACEBOOK_APP_ID,
                    'client_secret': settings.FACEBOOK_APP_SECRET,
                    'access_token': short_lived_token,
                }
            )
            
            long_lived_data = long_lived_response.json()
            
            if 'error' in long_lived_data:
                error_msg = long_lived_data['error'].get('message', 'Long-lived token exchange failed')
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] Long-lived token error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason={error_msg}"
                )
            
            long_lived_token = long_lived_data.get('access_token')
            expires_in = long_lived_data.get('expires_in', 5184000)  # Default 60 days
            token_expiry = timezone.now() + timedelta(seconds=expires_in)
            
            print(f"✅ [INSTAGRAM OAUTH CALLBACK] Got long-lived token (expires in {expires_in}s = ~{expires_in//86400} days)")
            
            # Get user's Instagram account details using Instagram API
            print(f"🔄 [INSTAGRAM OAUTH CALLBACK] Fetching Instagram account details...")
            account_response = requests.get(
                f"https://graph.instagram.com/v19.0/{instagram_user_id}",
                params={
                    'fields': 'username,name,profile_picture_url,biography,website,followers_count,media_count',
                    'access_token': long_lived_token,
                }
            )
            
            account_data = account_response.json()
            print(f"🔍 [INSTAGRAM OAUTH CALLBACK] Account details response: {account_data}")  # Debug
            
            if 'error' in account_data:
                error_msg = account_data['error'].get('message', 'Failed to get Instagram account details')
                print(f"❌ [INSTAGRAM OAUTH CALLBACK] Account fetch error: {error_msg}")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason={error_msg}"
                )
            
            # Extract Instagram account details
            instagram_username = account_data.get('username', account_data.get('name', 'Unknown'))
            profile_picture = account_data.get('profile_picture_url', '')
            biography = account_data.get('biography', '')
            followers = account_data.get('followers_count', 0)
            
            if not instagram_user_id:
                print(f"⚠️  [INSTAGRAM OAUTH CALLBACK] No Instagram account found")
                return HttpResponseRedirect(
                    f"{frontend_url}/platforms"
                    f"?oauth_error=true&platform=instagram&reason=no_accounts"
                )
            
            print(f"✅ [INSTAGRAM OAUTH CALLBACK] Retrieved Instagram account: {instagram_username}")
            
            # Store as UserSocialAccount
            print(f"\n📝 [INSTAGRAM OAUTH CALLBACK] Processing account: {instagram_username}")
            
            account, created = UserSocialAccount.objects.update_or_create(
                user=user,
                platform='instagram',
                account_id=instagram_user_id,
                defaults={
                    'access_token': long_lived_token,
                    'account_name': instagram_username,
                    'account_email': '',
                    'profile_picture_url': profile_picture,
                    'token_expiry': token_expiry,
                    'is_token_valid': True,
                    'scopes': ['instagram_basic', 'instagram_manage_insights', 'pages_read_engagement', 'pages_show_list'],
                    'api_calls_made': 0,
                    'api_calls_limit': 1000,  # Free tier
                }
            )
            
            status_text = "Created" if created else "Updated"
            print(f"✅ [INSTAGRAM OAUTH CALLBACK] {status_text} UserSocialAccount for {instagram_username}")
            
            # Also create/update Platform record for backwards compatibility
            platform, _ = Platform.objects.update_or_create(
                user=user,
                name='instagram',
                channel_id=instagram_user_id,
                defaults={
                    'channel_name': instagram_username,
                    'channel_url': f"https://instagram.com/{instagram_username}",
                    'is_active': True,
                    'metadata': {
                        'account_id': instagram_user_id,
                        'username': instagram_username,
                        'access_token': long_lived_token,
                        'biography': biography,
                        'followers': followers,
                        'oauth_version': 'user-specific',
                        'account_type': 'instagram_personal',  # Can be extended for business accounts
                    }
                }
            )
            
            print(f"\n✅ [INSTAGRAM OAUTH CALLBACK] OAuth callback completed!")
            print(f"   User: {user.username}")
            print(f"   Instagram: {instagram_username}")
            print(f"   Token expiry: {token_expiry.isoformat()}")
            print(f"   Days until expiry: {(token_expiry - timezone.now()).days}")
            
            # Redirect to platforms page with success indicator
            return HttpResponseRedirect(
                f"{frontend_url}/platforms"
                f"?oauth_success=true&platform=instagram&count=1"
            )
            
        except Exception as e:
            print(f"❌ [INSTAGRAM OAUTH CALLBACK] Exception: {str(e)}")
            import traceback
            traceback.print_exc()
            logger.error(f"Instagram OAuth callback error: {e}", exc_info=True)
            
            return HttpResponseRedirect(
                f"{frontend_url}/platforms"
                f"?oauth_error=true&platform=instagram&reason=internal_error"
            )
