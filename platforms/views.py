from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from .models import AddPlatform

class PlatformListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            platforms = AddPlatform.objects.filter(user=request.user).order_by("-created_at")
            data = []
            for platform in platforms:
                data.append({
                    "id": platform.id,
                    "name": platform.name,
                    "channel_url": platform.channel_url,
                    "channel_id": platform.channel_id,
                    "created_at": platform.created_at,
                })
            return Response({
                "message": "Platforms fetched successfully",
                "data": data
            }, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request):
        try:
            data = request.data
            name = data.get("name")
            channel_url = data.get("channel_url")
            channel_id = data.get("channel_id")

            if not name or not channel_url or not channel_id:
                return Response({"message": "All fields required"}, status=status.HTTP_400_BAD_REQUEST)

            AddPlatform.objects.create(
                user=request.user,
                name=name,
                channel_url=channel_url,
                channel_id=channel_id
            )
            return Response({"message": "Platform Added Successfully"}, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

class PlatformDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        try:
            platform = AddPlatform.objects.get(pk=pk, user=request.user)
            platform.delete()
            return Response({"message": "Platform deleted successfully"}, status=status.HTTP_200_OK)
        except AddPlatform.DoesNotExist:
            return Response({"message": "Platform not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"message": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
